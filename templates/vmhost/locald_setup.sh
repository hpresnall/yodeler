# on next boot, when libvirt is running, configure it
cp /root/yodeler/$HOSTNAME/libvirt.start /etc/local.d/
chmod +x /etc/local.d/libvirt.start

echo "Rebooting to run final libvirt configuration"
reboot
