mkdir -p  /root/yodeler/logs
exec >> /root/yodeler/logs/$HOSTNAME 2>&1

# configure storage
mkdir $VM_IMAGES_PATH
chown nobody:libvirt $VM_IMAGES_PATH
chmod 755 $VM_IMAGES_PATH
virsh pool-define-as --name vmstorage --type dir --target $VM_IMAGES_PATH
virsh pool-autostart vmstorage
virsh pool-start vmstorage

# remove default DHCP network
virsh net-destroy default
virsh net-undefine default

DIR=/root/yodeler/$HOSTNAME
