# block all incoming traffic until awall is configured
echo "Blocking incoming traffic before setup"
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

/root/yodeler/$HOSTNAME/setup.sh

# remove from local.d so setup is only run once
rm $$0
