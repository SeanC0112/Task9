if [ -d "./CARLA_LATEST" ]; then
    echo "Directory exists."
else
    wget https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_0.9.16.tar.gz -P .
    mkdir -p ./CARLA_LATEST
    echo "Extracting Carla to Desktop/CARLA_LATEST/"
    tar -xvf ./CARLA_0.9.16.tar.gz -C ./CARLA_LATEST > /dev/null
    rm ./CARLA_0.9.16.tar.gz
fi


apt install python3.12 python3.12-venv python3.12-dev -y
apt install pip -y
# apt-get install -y swig

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

./CARLA_LATEST/CarlaUE4.sh -carla-rpc-port=2001

python3 main.py birdseye