# setup additional ip6tables rules
# rules to block incoming already set up in yodel.sh
# iptables save will be called on shutdown

# ensure default policy
ip6tables -P INPUT DROP
ip6tables -P FORWARD DROP

# forward from fakeisp to fakeinternet
ip6tables -A FORWARD -i $FAKEINTERNET_IFACE -o $FAKEISP_IFACE -m state --state RELATED,ESTABLISHED -j ACCEPT
ip6tables -A FORWARD -i $FAKEISP_IFACE -o $FAKEINTERNET_IFACE -j ACCEPT
ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
#  to forward all traffic: ip6tables -A FORWARD -i $FAKEINTERNET_IFACE -o $FAKEISP_IFACE -j ACCEPT

# allow ping & SSH
ip6tables -A INPUT -p ipv6-icmp -j ACCEPT
ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT

# allow DHCP6
ip6tables -A INPUT -p udp --dport 546 -j ACCEPT
ip6tables -A INPUT -p udp --dport 547 -j ACCEPT

rc-service ip6tables save
