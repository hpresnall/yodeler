# temporarily change the umask
# VM creation with a 027 umask results in the nonroot user not being able to
# run commands due to library permission / loader issues
umask 022

# create the virtual machine
# run setup.sh inside a chroot of the VM's filesystem
log "Building VM image for '$HOSTNAME'"
/home/$USER/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size ${DISK_SIZE_MB}M \
  --repositories-file /etc/apk/repositories \
  --packages "$$(cat $$DIR/packages)" \
  --script-chroot \
  $VM_IMAGES_PATH/$HOSTNAME.img \
  $$DIR/setup.sh

# if successful, define the VM
if [ "$$?" = "0" ]; then
  log "Creating VM definition for '$HOSTNAME'"
  virsh define $$DIR/$HOSTNAME.xml

  # if successful, set the image perms & autostart the VM
  if [ "$$?" = "0" ]; then
    chmod 660 $VM_IMAGES_PATH/$HOSTNAME.img
    chown root:libvirt $VM_IMAGES_PATH/$HOSTNAME.img

    virsh autostart $HOSTNAME

    if [ "$$1" = "start" ]; then
      log "Starting VM '$HOSTNAME'"
      virsh start $HOSTNAME
    fi
  else
    log "Installation did not complete successfully; please see $$LOG for more info"
  fi
else
  log "Installation did not complete successfully; please see $$LOG for more info"
fi