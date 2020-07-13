mkdir -p  /root/yodeler/logs

# block all incoming traffic until awall is configured
echo "Blocking incoming traffic before setup" >> /root/yodeler/logs/$HOSTNAME 2>&1 
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

/root/yodeler/$HOSTNAME/setup.sh >> /root/yodeler/logs/$HOSTNAME 2>&1

# remove from local.d so setup is only run once
rm $$0

# on next boot, when libvirt is running, configure it
cp /root/yodeler/$HOSTNAME/libvirt.start /etc/local.d/
chmod +x /etc/local.d/libvirt.start

reboot
