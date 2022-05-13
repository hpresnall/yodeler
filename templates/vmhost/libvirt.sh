echo "Configuring libvirt"

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
rc-update add libvirtd
rc-update add dbus

# add alpine-make-vm-images for creating new VMs
cd /home/$USER
git clone https://github.com/alpinelinux/alpine-make-vm-image.git
chown -R $USER:$USER alpine-make-vm-image
