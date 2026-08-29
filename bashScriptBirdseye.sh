apt install python3.12 python3.12-venv python3.12-dev -y
apt install pip -y
# apt-get install -y swig

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

python3 main.py birdseye