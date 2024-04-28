#!/bin/sh
# this should be run when chrooted in the shared build image of the vmhost
set -o errexit

apk -q --no-progress add git

cd build

if [ -d hosts ]; then
  cd hosts
  # clean up from any previous builds
  git reset --hard
  git pull
else
  git clone --depth=1 --single-branch --branch=master https://github.com/StevenBlack/hosts.git
  cd hosts
fi

apk -q --no-progress add python3 py-requests py-flake8 lua

# build hosts file
python3 updateHostsFile.py --auto --skipstatichosts
# use hosts file to create lua script
python3 /tmp/create_lua_blackhole.py hosts

rm hosts
mv blackhole.lua /tmp