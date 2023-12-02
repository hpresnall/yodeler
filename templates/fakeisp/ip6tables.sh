# setup basic ip6tables rules

# block incoming
ip6tables -P INPUT DROP
ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# allow ping & SSH
ip6tables -A INPUT -p icmp --icmp-type echo-request -j ACCEPT
ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT

rc-service ip6tables save
