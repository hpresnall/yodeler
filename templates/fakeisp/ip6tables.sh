# setup basic ip6tables rules

# block incoming already set up in yodel.sh
# these rules will also be saved

# allow ping & SSH
ip6tables -A INPUT -p ipv6-icmp -j ACCEPT
ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT

# allow DHCP6
ip6tables -A INPUT -p udp --dport 546 -j ACCEPT
ip6tables -A INPUT -p udp --dport 547 -j ACCEPT

rc-service ip6tables save
