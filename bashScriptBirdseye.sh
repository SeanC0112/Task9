#!/usr/bin/env bash
set -euo pipefail
trap 'echo "FATAL: script failed at line $LINENO (exit $?)"' ERR

cd ..

export SDL_AUDIODRIVER=dummy
export XDG_RUNTIME_DIR=/tmp/runtime-carlauser
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

if [ -d "./CARLA_LATEST" ]; then
    echo "Directory exists."
else
    apt update && apt install -y curl
    curl -L -o carla_0.9.16.tar.gz \
        "https://tiny.carla.org/carla-0-9-16-linux"
    mkdir -p ./CARLA_LATEST
    echo "Extracting Carla to CARLA_LATEST/"
    tar -xvf ./carla_0.9.16.tar.gz -C ./CARLA_LATEST > /dev/null
    rm ./carla_0.9.16.tar.gz
fi

apt install python3.12 python3.12-venv python3.12-dev -y
apt install pip -y

if [ -d "./venv" ]; then
    source venv/bin/activate
else
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
fi
pip install --no-cache-dir -r Task9/requirements.txt

id -u carlauser &>/dev/null || useradd -m carlauser
chown -R carlauser:carlauser . "$XDG_RUNTIME_DIR"

CARLA_LOG=/tmp/carla_launch.log
su carlauser -c "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR SDL_AUDIODRIVER=dummy ./CARLA_LATEST/CarlaUE4.sh -carla-rpc-port=2001 -RenderOffScreen" \
    > "$CARLA_LOG" 2>&1 &
CARLA_PID=$!

echo "Waiting for CARLA RPC port 2001 (this can take 1-3 min on a cold shader cache)..."
TIMEOUT=180
for i in $(seq 1 "$TIMEOUT"); do
    if ! kill -0 "$CARLA_PID" 2>/dev/null; then
        echo "FATAL: CarlaUE4 process died during startup. Wrapper stdout:"
        cat "$CARLA_LOG"
        exit 1
    fi
    if python3 -c "import socket; s=socket.create_connection(('127.0.0.1',2001),timeout=1)" 2>/dev/null; then
        echo "CARLA is up after ${i}s."
        break
    fi
    sleep 1
    if [ "$i" -eq "$TIMEOUT" ]; then
        echo "FATAL: CARLA did not open port 2001 within ${TIMEOUT}s."
        echo "--- Wrapper stdout ---"
        cat "$CARLA_LOG"
        echo "--- Is the engine binary even running? ---"
        ps aux | grep -i carla || echo "No CarlaUE4 process found in ps output."
        echo "--- Actual Unreal Engine log (most recently modified) ---"
        UE_LOG=$(find ./CARLA_LATEST -iname "*.log" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
        if [ -n "${UE_LOG:-}" ]; then
            echo "Found: $UE_LOG"
            tail -n 150 "$UE_LOG"
        else
            echo "No .log files found anywhere under CARLA_LATEST — engine may have failed before writing any log."
        fi
        kill "$CARLA_PID" 2>/dev/null || true
        exit 1
    fi
done

python3 Task9/main.py birdseye