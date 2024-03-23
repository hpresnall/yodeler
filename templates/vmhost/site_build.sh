# setup shared build image
# other vms can use this before chrooting
if [ ! -f "$$SITE_DIR/build.img" ]; then
  #log "Creating shared build image"
  $VM_IMAGES_PATH/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size 1024M \
  --repositories-file /etc/apk/repositories \
  "$$SITE_DIR/build.img"
fi

BUILD_MOUNT="/media/${SITE_NAME}_build"
mkdir -p $$BUILD_MOUNT
mount -o loop "$$SITE_DIR/build.img" "$$BUILD_MOUNT"

cd "$$BUILD_MOUNT"
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
