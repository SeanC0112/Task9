if [ -d "./CARLA_LATEST" ]; then
    echo "Directory exists."
else
    curl -L -O "https://github.com/carla-simulator/carla/archive/refs/tags/0.9.16.tar.gz"
    mkdir -p ./CARLA_LATEST
    echo "Extracting Carla to Desktop/CARLA_LATEST/"
    tar -xvf ./carla_0.9.16.tar.gz -C ./CARLA_LATEST > /dev/null
    rm ./carla_0.9.16.tar.gz
fi



apt install python3.12 python3.12-venv python3.12-dev -y
apt install pip -y
# apt-get install -y swig

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

./CARLA_LATEST/CarlaUE4.sh -carla-rpc-port=2001

python3 main.py baseline