# configure build environment for any setup that requires non-apk packages or additional work to configure
# this images file will be will be shared at the site level
# it will be mounted so that setup can copy files and chroot into it, if needed
$$BUILD_DIR=$$SITE_DIR/build

# only create if needed
if [ ! -f "$$BUILD_DIR/build.img" ]; then
  if [ ! -d "$$BUILD_DIR/alpine-make-vm-image"]; then
    # add alpine-make-vm-images for creating new VMs
    log "Installing alpine-make-vm-image"
    cd $$BUILD_DIR
    apk -q --no-progress add git
    git clone --depth=1 --single-branch --branch=master https://github.com/alpinelinux/alpine-make-vm-image.git
    cd alpine-make-vm-image
    if [ -f $$DIR/patch ]; then
        git apply $$DIR/make-vm-image-patch
    fi
  fi

  # create a build image just like a VM
  log "Creating shared build image $$SITE_DIR/build.img"
  $$BUILD_DIR/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size 4096M \
  --repositories-file /etc/apk/repositories \
  "$$BUILD_DIR/build.img"
else
  log "Using existing build image $$BUILD_DIR/build.img"
fi

SITE_BUILD_MOUNT="/media/${SITE_NAME}_build"

# only mount once per yodel; vms built by the same vm host will share config
if [ -n "$$(mount | grep $$SITE_BUILD_MOUNT)" ]; then
  log "Build image already mounted at $$SITE_BUILD_MOUNT"
  exit
fi

mkdir -p $$SITE_BUILD_MOUNT
mount -o loop "$$SITE_DIR/build.img" "$$SITE_BUILD_MOUNT"

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

cd $$DIR
