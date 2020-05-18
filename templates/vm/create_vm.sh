# <vmhost>/bootstrap.sh should have downloaded all the required APKs
# ensure they are used by alpine-make-vm-image
export APK_OPTS="$APK_OPTS"

# create the virtual machine
# run setup.sh inside a chroot of the VM's filesystem
/home/$USER/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size ${DISK_SIZE_MB}M \
  --packages `cat $$DIR/packages` \
  --script-chroot $$DIR/setup.sh \
  $VM_IMAGES_PATH/$HOSTNAME.img

# if successful, define the VM
if [ "$$?" = "0" ]; then
  virsh define $$DIR/$HOSTNAME.xml

  # if successful, start the VM
  if [ "$$?" = "0" ]; then
    chmod 660 $VM_IMAGES_PATH/$HOSTNAME.img
    chown root:libvirt $VM_IMAGES_PATH/$HOSTNAME.img

    virsh autostart $HOSTNAME
    virsh start $HOSTNAME
  fi
fi