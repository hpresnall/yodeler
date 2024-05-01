# setup shared build image
# other vms can use this before chrooting
if [ ! -f "$$SITE_DIR/build.img" ]; then
  log "Creating shared build image $$SITE_DIR/build.img"
  $VM_IMAGES_PATH/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size 4096M \
  --repositories-file /etc/apk/repositories \
  "$$SITE_DIR/build.img"
else
  log "Using existing build image $$SITE_DIR/build.img"
fi

SITE_BUILD_IMG="/media/${SITE_NAME}_build"

if [ -n "$$(mount | grep $$SITE_BUILD_IMG)" ]; then
  log "Build image already mounted at $$SITE_BUILD_IMG"
  exit
fi

log "Setting up shared build image"

mkdir -p $$SITE_BUILD_IMG
mount -o loop "$$SITE_DIR/build.img" "$$SITE_BUILD_IMG"

cd "$$SITE_BUILD_IMG"
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
log "Build image mounted at $$SITE_BUILD_IMG"

cd - > /dev/null 2>&1

export SITE_BUILD_IMG
