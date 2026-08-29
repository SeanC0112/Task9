apt install python3.10 python3.10-venv python3.10-dev -y
apt install pip -y
# apt-get install -y swig

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

python3 main.py birdseye