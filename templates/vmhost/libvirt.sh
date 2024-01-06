log "Setting up libvirt"

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
install -m 640 -D /etc/libvirt/libvirt.conf /home/$USER/.config/libvirt/libvirt.conf
chown -R "$USER:$USER" /home/$USER/.config
sed -i -e "s/#uri_default/uri_default/g" /home/$USER/.config/libvirt/libvirt.conf

# run everything at startup
rc-update add dbus default
rc-update add polkit default
rc-update add libvirtd default
rc-update add libvirt-guests default

# shutdown VMs when the server shuts down
echo "LIBVIRT_SHUTDOWN=\"shutdown\"
LIBVIRT_MAXWAIT=\"120\"
LIBVIRT_NET_SHUTDOWN=\"no\"" >> /etc/conf.d/libvirt-guests

log "Starting libvirt"
# libvirt needs networking; make libvirt think it is started
# continue to use the installer network instead
mkdir -p /var/run/openrc/started
ln -s /etc/init.d/networking /var/run/openrc/started/networking

rc-service dbus start
rc-service polkit start
rc-service libvirtd start

# wait for libvirt to start
virsh list > /dev/null 2>&1
while [ "$$?" -ne 0 ]; do
    sleep 1
    virsh list > /dev/null 2>&1
done

log "Configuring libvirt storage"
mkdir -p $VM_IMAGES_PATH/backup
mkdir -p $VM_IMAGES_PATH/shared
chown -R nobody:libvirt $VM_IMAGES_PATH
chmod 755 -R $VM_IMAGES_PATH
virsh pool-define-as --name vmstorage --type dir --target $VM_IMAGES_PATH
virsh pool-autostart vmstorage
virsh pool-start vmstorage

# needed for pci passthrough
echo vfio_iommu_type1 > /etc/modules-load.d/iommu

log "Installing alpine-make-vm-image"
# add alpine-make-vm-images for creating new VMs
cd $VM_IMAGES_PATH
git clone --depth=1 --single-branch --branch=master https://github.com/alpinelinux/alpine-make-vm-image.git
chown -R nobody:libvirt alpine-make-vm-image
cd alpine-make-vm-image
if [ -f $$DIR/patch ]; then
    git apply $$DIR/patch
fi

log "Adding libvirt hook scripts"
# add hook scripts for disabling ipv6 on vswitch and vm interfaces
mkdir -p /etc/libvirt/hooks
chmod 750 /etc/libvirt/hooks
chown root:libvirt /etc/libvirt/hooks
install -o root -g libvirt -m 750 $$DIR/network_hook /etc/libvirt/hooks/network
install -o root -g libvirt -m 750 $$DIR/qemu_hook /etc/libvirt/hooks/qemu

log "Configuring libvirt networks"
# remove default DHCP network
virsh net-destroy default
virsh net-undefine default
