#!/bin/sh
# create log function if running outside of Yodeler
type log >/dev/null

if [ "$$?" != "0" ]; then
  log () {
    echo $$*
  }
fi

if [ -z $$SITE_DIR ]; then
  DIR=$$(cd -P -- "$$(dirname -- "$$0")" && pwd -P)
  SITE_DIR=$$(realpath $$DIR/..)
fi;

# configure build environment for any setup that requires non-apk packages or additional work to configure
# this images file will be will be shared at the site level
# it will be mounted so that setup can copy files and chroot into it, if needed
SITE_BUILD_DIR=$$SITE_DIR/site_build
mkdir -p $$SITE_BUILD_DIR

if [ ! -d "$$SITE_BUILD_DIR/alpine-make-vm-image" ]; then
  # add alpine-make-vm-images for creating new VMs
  log "Installing alpine-make-vm-image"
  cd $$SITE_BUILD_DIR
  apk -q --no-progress add git
  git clone --depth=1 --single-branch --branch=master https://github.com/alpinelinux/alpine-make-vm-image.git
  cd alpine-make-vm-image
  if [ -f $$SITE_BUILD_DIR/make-vm-image-patch ]; then
      git apply $$SITE_BUILD_DIR/make-vm-image-patch
  fi
fi

# reuse existing image
# build scripts should check for existing builds and handle as needed
if [ ! -f "$$SITE_BUILD_DIR/site_build.img" ]; then
  # create a build image just like a VM
  log "Creating shared build image '$$SITE_DIR/site_build.img'"
  $$SITE_BUILD_DIR/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size 2048M \
  --repositories-file /etc/apk/repositories \
  "$$SITE_BUILD_DIR/site_build.img"
else
  log "Using existing build image $$SITE_BUILD_DIR/site_build.img"
fi

SITE_BUILD_MOUNT="/media/${SITE_NAME}_build"

# only mount once per yodel; vms built by the same vm host will share config
if [ -n "$$(mount | grep $$SITE_BUILD_MOUNT)" ]; then
  log "Build image already mounted at $$SITE_BUILD_MOUNT"
else
  mkdir -p $$SITE_BUILD_MOUNT
  mount -o loop "$$SITE_BUILD_DIR/site_build.img" "$$SITE_BUILD_MOUNT"

  # all scripts should put work into /build
  cd "$$SITE_BUILD_MOUNT"
  mkdir -p build

  # use host's resolv
  cp /etc/resolv.conf etc

  # setup APK cache for chroot
  # create real dir and symlink in build; bind mount host's cache dir
  mkdir -p tmp/apk_cache etc/apk
  if [ ! -L etc/apk/cache ]; then
    # will be /tmp inside chroot
    ln -s /tmp/apk_cache etc/apk/cache
  fi
  mount --bind "$$(realpath /etc/apk/cache)" tmp/apk_cache
  log "Build image mounted at $$SITE_BUILD_MOUNT"

fi

cd $$DIR