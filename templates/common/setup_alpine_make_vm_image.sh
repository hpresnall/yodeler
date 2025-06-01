SITE_BUILD_DIR=$SITE_DIR/build
mkdir -p $SITE_BUILD_DIR

if [ ! -d "$SITE_BUILD_DIR/alpine-make-vm-image" ]; then
  # add alpine-make-vm-image for creating new VMs
  log "Installing alpine-make-vm-image"
  cd $SITE_BUILD_DIR
  apk -q --no-progress add git
  git clone --depth=1 --single-branch --branch=master https://github.com/alpinelinux/alpine-make-vm-image.git
  cd alpine-make-vm-image
  if [ -f $SITE_BUILD_DIR/make-vm-image-patch ]; then
      git apply $SITE_BUILD_DIR/make-vm-image-patch
  fi
fi