VMHOST=$VMHOST
HOST_BACKUP=$HOST_BACKUP
AUTOSTART=$AUTOSTART

if [ "$$VMHOST" != "$$(hostname)" ]; then
  log "Can only setup VM '$HOSTNAME' on VM host '$$VMHOST'"
  exit 1
fi

log "Setting up environment to build VM '$HOSTNAME'"

# copy files in /tmp/$HOSTNAME into /tmp on the VM using --fs-skel-dir param
SETUP_TMP=/tmp/$HOSTNAME/tmp
mkdir -p $$SETUP_TMP
rm -f $$SETUP_TMP/envvars
# export START_TIME in chroot to use the same LOG_DIR this script is already using
echo "export START_TIME=$$START_TIME" > $$SETUP_TMP/envvars

# expose any backups to the VM
if [ -d $$SITE_DIR/backup/$HOSTNAME]; then
  log "Copying backup into VM"
  mkdir $$SETUP_TMP/backup
  cp -r $$SITE_DIR/backup/$HOSTNAME/* $$SETUP_TMP/backup
  # note $$SITE_DIR/backup/$HOSTNAME still exists but will not be current!
fi

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
$$SITE_DIR/site_build/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size ${DISK_SIZE_MB}M \
  --repositories-file /etc/apk/repositories \
  --packages "$$(cat $$DIR/packages)" \
  --fs-skel-dir "$$SETUP_TMP/.." \
  --script-chroot \
  $VM_IMAGES_PATH/$HOSTNAME.img \
  $$DIR/setup.sh

RESULT=$$?

# restore original logging on error
trap error ERR
set -o errexit

$AFTER_CHROOT

rm -rf $$SETUP_TMP

if [ "$$RESULT" != 0 ]; then
  log "Unsuccessful Yodel for vm '$HOSTNAME'; see $$LOG for full details"
  exit 1
fi

# define the VM
log "Creating VM definition"
virsh define $$DIR/$HOSTNAME.xml

# set the image perms & create the share & backup directories
chown qemu:kvm $VM_IMAGES_PATH/$HOSTNAME.img
chmod 660 $VM_IMAGES_PATH/$HOSTNAME.img

if [ "$$HOST_BACKUP" = "True" ]; then
  log "Creating backup directory on the vmhost"
  mkdir -p $VM_IMAGES_PATH/backup/$HOSTNAME
  chown nobody:libvirt $VM_IMAGES_PATH/backup/$HOSTNAME
  chmod 750 $VM_IMAGES_PATH/backup/$HOSTNAME
fi

# (auto)start the VM if configured
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