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
install -o $USER -g $USER -m 640 -D /etc/libvirt/libvirt.conf /home/$USER/.config/libvirt/libvirt.conf
sed -i -e "s/#uri_default/uri_default/g" /home/$USER/.config/libvirt/libvirt.conf

# run everything at startup
rc-update add dbus
rc-update add polkit
rc-update add libvirtd
rc-update add libvirt-guests

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
mkdir -p $VM_IMAGES_PATH
chown nobody:libvirt $VM_IMAGES_PATH
chmod 755 $VM_IMAGES_PATH
virsh pool-define-as --name vmstorage --type dir --target $VM_IMAGES_PATH
virsh pool-autostart vmstorage
virsh pool-start vmstorage

log "Configuring libvirt networks"
# remove default DHCP network
virsh net-destroy default
virsh net-undefine default

# add alpine-make-vm-images for creating new VMs
log "Installing alpine-make-vm-image"
cd $VM_IMAGES_PATH
git clone --depth=1 --single-branch --branch=master https://github.com/alpinelinux/alpine-make-vm-image.git
chown -R nobody:libvirt alpine-make-vm-image
cd alpine-make-vm-image
if [ -f $$DIR/patch ]; then
    git apply $$DIR/patch
fi
