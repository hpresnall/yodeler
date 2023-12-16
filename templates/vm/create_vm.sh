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
log "Building VM image for '$HOSTNAME'"
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

# if successful, define the VM
if [ "$$?" = "0" ]; then
  log "Creating VM definition for '$HOSTNAME'"
  virsh define $$DIR/$HOSTNAME.xml

  # if successful, set the image perms & create the share & backup directories
  # (auto)start the VM if configured
  if [ "$$?" = "0" ]; then
    chown qemu:kvm $VM_IMAGES_PATH/$HOSTNAME.img
    chmod 660 $VM_IMAGES_PATH/$HOSTNAME.img

    if [ "$HOST_BACKUP" = "True" ]; then
      log "Creating backup directory"
      mkdir -p $VM_IMAGES_PATH/backup/$HOSTNAME
      chown nobody:libvirt $VM_IMAGES_PATH/backup/$HOSTNAME
      chmod 750 $VM_IMAGES_PATH/backup/$HOSTNAME
    fi

    if [ "$AUTOSTART" = "True" ]; then
      virsh autostart $HOSTNAME
    fi

    if [ "$$1" = "start" ]; then
      log "Starting VM '$HOSTNAME'"
      virsh start $HOSTNAME
    fi
  fi
fi