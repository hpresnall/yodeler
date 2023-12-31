HOST_BACKUP=$HOST_BACKUP
AUTOSTART=$AUTOSTART

log "Creating VM for '$HOSTNAME'"

# copy files in /tmp/$HOSTNAME into /tmp on the VM using --fs-skel-dir param
mkdir -p /tmp/$HOSTNAME/tmp
rm -f /tmp/$HOSTNAME/tmp/envvars
touch /tmp/$HOSTNAME/tmp/envvars

$BEFORE_CHROOT

# temporarily change the umask
# VM creation with a 027 umask results in the nonroot user not being able to
# run commands due to library permission / loader issues
umask 022

# create the virtual machine
# run setup.sh inside a chroot of the VM's filesystem
log "Building VM image"
# log differently if setup fails
trap - ERR
set +o errexit
$VM_IMAGES_PATH/alpine-make-vm-image/alpine-make-vm-image \
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
trap exception ERR
set -o errexit

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

if [ "$$1" = "start" ]; then
  log "Starting VM '$HOSTNAME'"
  virsh start $HOSTNAME
fi

log "Successful Yodel for '$HOSTNAME'!"