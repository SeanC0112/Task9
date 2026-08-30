cd ..
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
    pip install -r Task9/requirements.txt
fi


id -u carlauser &>/dev/null || useradd -m carlauser
chown -R carlauser:carlauser .

# launch Carla server as non-root, backgrounded
su carlauser -c "./CARLA_LATEST/CarlaUE4.sh -carla-rpc-port=2001 -RenderOffScreen" &
CARLA_PID=$!

sleep 30

python3 Task9/main.py baseline