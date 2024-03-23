#!/bin/sh
# build pi-hole like hosts file
# this will be run chrooted into the shared build image of the vmhost
set -o errexit

apk add git

cd build

if [ -d hosts ]; then
  cd hosts
  git pull
else
  git clone --depth=1 --single-branch --branch=master https://github.com/StevenBlack/hosts.git
  cd hosts
fi

apk add python3 py-requests py-flake8
python3 updateHostsFile.py --auto --skipstatichosts

cp hosts /tmp