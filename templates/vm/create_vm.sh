# temorarily change the umask
# VM creation with a 027 umask results in the nonroot user not being able to
# run commands due to library permission / loader issues
umask 022

# create the virtual machine
# run setup.sh inside a chroot of the VM's filesystem
echo "Building VM image for $HOSTNAME"
/home/$USER/alpine-make-vm-image/alpine-make-vm-image \
  --image-format raw \
  --serial-console \
  --image-size ${DISK_SIZE_MB}M \
  --packages "$$(cat $$DIR/packages)" \
  --script-chroot \
  $VM_IMAGES_PATH/$HOSTNAME.img \
  $$DIR/setup.sh

# if successful, define the VM
if [ "$$?" = "0" ]; then
  echo "Creating VM definition for $HOSTNAME"
  virsh define $$DIR/$HOSTNAME.xml

  # if successful, start the VM
  if [ "$$?" = "0" ]; then
    echo "Starting VM $HOSTNAME"
    chmod 660 $VM_IMAGES_PATH/$HOSTNAME.img
    chown root:libvirt $VM_IMAGES_PATH/$HOSTNAME.img

    virsh autostart $HOSTNAME
    virsh start $HOSTNAME
  fi
fi