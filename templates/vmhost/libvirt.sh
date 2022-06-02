echo "Configuring libvirt"

# remove CEPH storage option; it has caused libvirt startup issues in the past
rm /usr/lib/libvirt/storage-backend/libvirt_storage_backend_rbd.so

# more secure sockets
echo "unix_sock_group = \"libvirt\"
unix_sock_ro_perms = \"0770\"
unix_sock_rw_perms = \"0770\"" >> /etc/libvirt/libvirtd.conf

# run qemu as qemu:kvm for security and access to /dev/kvm
# qemu user should already be added by libvirt install
addgroup qemu kvm
echo "user = \"qemu\"
group = \"kvm\"" >> /etc/libvirt/qemu.conf

# give user access and allow it to see root level VMs
addgroup $USER libvirt
install -o $USER -g $USER -m 640 -D /etc/libvirt/libvirt.conf /home/$USER/.config/libvirt/libvirt.conf
sed -i -e "s/#uri_default/uri_default/g" /home/$USER/.config/libvirt/libvirt.conf

# run everything at startup
rc-update add dbus
rc-update add polkit
rc-update add libvirtd

# add alpine-make-vm-images for creating new VMs
cd /home/$USER
rootinstall $$DIR/resolv.orig /etc/resolv.conf
git clone https://github.com/alpinelinux/alpine-make-vm-image.git
chown -R $USER:$USER alpine-make-vm-image
rootinstall $$DIR/resolv.orig /etc

echo "Starting libvirt services"
# libvirt needs networking, but do not start the openvswitch configured networking
# continue to use the installer network, but make libvirt think networking is started
mkdir -p /var/run/openrc/started
ln -s /etc/init.d/networking /var/run/openrc/started/networking

rc-service dbus start
rc-service polkit start
rc-service libvirtd start

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

DIR=/root/$SITE/$HOSTNAME
