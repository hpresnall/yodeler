# setup basic iptables rules

# block incoming
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# allow ping & SSH
iptables -A INPUT -p icmp --icmp-type echo-request -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -j ACCEPT

# NAT from fakeisp to fakeinternet
iptables -A POSTROUTING  -t nat  -o $FAKEINTERNET_IFACE -j MASQUERADE
iptables -A FORWARD -i $FAKEINTERNET_IFACE -o $FAKEISP_IFACE -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i $FAKEISP_IFACE -o $FAKEINTERNET_IFACE -j ACCEPT

rc-service iptables save