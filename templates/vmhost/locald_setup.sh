# block all incoming traffic until awall is configured
echo "Blocking incoming traffic before setup"
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

/root/yodeler/$HOSTNAME/setup.sh

# remove from local.d so setup is only run once
rm $$0

# on next boot, when libvirt is running, configure it
cp /root/yodeler/$HOSTNAME/libvirt.start /etc/local.d/
chmod +x /etc/local.d/libvirt.start

echo "Rebooting after installing final libvirt setup in local.d"
reboot
