set +o errexit # vm may not be running
echo "Shutting down VM '$HOSTNAME'"
virsh shutdown $HOSTNAME
set -o errexit
virsh undefine $HOSTNAME
rm $VM_IMAGES_PATH/$HOSTNAME.img
echo "Deleted VM '$HOSTNAME'"