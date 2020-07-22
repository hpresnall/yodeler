echo "Configuring libvirt storage"
mkdir $VM_IMAGES_PATH
chown nobody:libvirt $VM_IMAGES_PATH
chmod 755 $VM_IMAGES_PATH
virsh pool-define-as --name vmstorage --type dir --target $VM_IMAGES_PATH
virsh pool-autostart vmstorage
virsh pool-start vmstorage

echo "Configuring libvirt networks"

# remove default DHCP network
virsh net-destroy default
virsh net-undefine default

DIR=/root/yodeler/$HOSTNAME
