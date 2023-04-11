echo "Shutting down VM '$HOSTNAME'"
virsh shutdown $HOSTNAME > /dev/null 2>&1
virsh undefine $HOSTNAME > /dev/null 2>&1
rm -f $VM_IMAGES_PATH/$HOSTNAME.img
echo "Deleted VM '$HOSTNAME'"