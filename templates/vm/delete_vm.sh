virsh destroy $HOSTNAME
virsh undefine $HOSTNAME
rm $VM_IMAGES_PATH/$HOSTNAME.img
echo "Deleted VM $HOSTNAME"