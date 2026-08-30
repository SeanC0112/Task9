#!/usr/bin/env bash
set -euo pipefail
trap 'echo "FATAL: script failed at line $LINENO (exit $?)"' ERR

cd ..

# --- silence ALSA / XDG warnings ---
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
# always install/sync deps, venv existing doesn't mean requirements are current
pip install --no-cache-dir -r Task9/requirements.txt

id -u carlauser &>/dev/null || useradd -m carlauser
chown -R carlauser:carlauser . "$XDG_RUNTIME_DIR"

su carlauser -c "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR SDL_AUDIODRIVER=dummy ./CARLA_LATEST/CarlaUE4.sh -carla-rpc-port=2001 -RenderOffScreen" &
CARLA_PID=$!

echo "Waiting for CARLA RPC port 2001..."
for i in $(seq 1 60); do
    if ! kill -0 "$CARLA_PID" 2>/dev/null; then
        echo "FATAL: CarlaUE4 process died during startup."
        exit 1
    fi
    if python3 -c "import socket; s=socket.create_connection(('127.0.0.1',2001),timeout=1)" 2>/dev/null; then
        echo "CARLA is up after ${i}s."
        break
    fi
    sleep 1
    if [ "$i" -eq 60 ]; then
        echo "FATAL: CARLA did not open port 2001 within 60s."
        kill "$CARLA_PID" 2>/dev/null || true
        exit 1
    fi
done

python3 Task9/main.py baseline