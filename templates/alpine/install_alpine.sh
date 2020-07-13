# alpine install will setup the network
# block all incoming traffic until awall is configured
echo "Blocking incoming traffic before setup"
apk -q add iptables
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# install Alpine with answerfile
echo "Installing Alpine to $ROOT_DEV"
setup-alpine -e -f $$DIR/answerfile
echo
echo "Alpine install complete"
