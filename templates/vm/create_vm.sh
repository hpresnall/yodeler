HOST_BACKUP=$HOST_BACKUP
AUTOSTART=$AUTOSTART

log "Setting up environment to build VM '$HOSTNAME'"

# copy files in /tmp/$HOSTNAME into /tmp on the VM using --fs-skel-dir param
SETUP_TMP=/tmp/$HOSTNAME/tmp
mkdir -p $$SETUP_TMP
rm -f $$SETUP_TMP/tmp/envvars
touch $$SETUP_TMP/envvars
# export START_TIME in chroot to use the same LOG_DIR this script is already using
echo "export START_TIME=$$START_TIME" >> $$SETUP_TMP/envvars

$BEFORE_CHROOT

# temporarily change the umask
# VM creation with a 027 umask results in the nonroot user not being able to
# run commands due to library permission / loader issues
umask 022

# log failure and exit if alpine-make-vm-image fails
trap - ERR
set +o errexit

log "Building VM image"
# create the virtual machine
# run setup.sh inside a chroot of the VM's filesystem
$$SITE_DIR/build/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size ${DISK_SIZE_MB}M \
  --repositories-file /etc/apk/repositories \
  --packages "$$(cat $$DIR/packages)" \
  --fs-skel-dir "/tmp/$HOSTNAME" \
  --script-chroot \
  $VM_IMAGES_PATH/$HOSTNAME.img \
  $$DIR/setup.sh

if [ "$$?" != 0 ]; then
  log "Unsuccessful Yodel for vm '$HOSTNAME'; see $$LOG for full details"
  exit 1
fi

# restore original logging on error
trap error ERR
set -o errexit

$AFTER_CHROOT

# define the VM
log "Creating VM definition"
virsh define $$DIR/$HOSTNAME.xml

# set the image perms & create the share & backup directories
# (auto)start the VM if configured
chown qemu:kvm $VM_IMAGES_PATH/$HOSTNAME.img
chmod 660 $VM_IMAGES_PATH/$HOSTNAME.img

if [ "$$HOST_BACKUP" = "True" ]; then
  log "Creating backup directory on the vmhost"
  mkdir -p $VM_IMAGES_PATH/backup/$HOSTNAME
  chown nobody:libvirt $VM_IMAGES_PATH/backup/$HOSTNAME
  chmod 750 $VM_IMAGES_PATH/backup/$HOSTNAME
fi

if [ "$$AUTOSTART" = "True" ]; then
  log "Setting autostart"
  virsh autostart $HOSTNAME
fi

# added for manual rebuilds to immediately start the vm
# not called during normal setup 
if [ "$$1" = "start" ]; then
  log "Starting VM '$HOSTNAME'"
  virsh start $HOSTNAME
fi

log "Successful Yodel for '$HOSTNAME'!"