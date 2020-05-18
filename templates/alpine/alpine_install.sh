# alpine install will setup the network
# block all incoming traffic until a better firewall is setup
echo "blocking incoming traffic before setup"
apk -q add iptables
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# install Alpine with answerfile
echo "installing Alpine to $ROOT_DEV"
setup-alpine -e -f $$DIR/answerfile > $$DIR/alpine_install.log