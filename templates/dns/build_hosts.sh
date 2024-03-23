#!/bin/sh
# build pi-hole like hosts file
apk add git

cd build

if [ -d hosts ]; then
  git pull
else
  git clone --depth=1 --single-branch --branch=master https://github.com/StevenBlack/hosts.git
fi

cd hosts

apk add python3 py-requests py-flake8
python3 updateHostsFile.py --auto --skipstatichosts

cp hosts /tmp