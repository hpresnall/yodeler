rc-service networking stop
rc-service iptables stop
rc-service ip6tables stop

rootinstall $$DIR/resolv.conf.final /etc/resolv.conf
rootinstall $$DIR/interfaces.final /etc/network/interfaces

mv $$DIR/awall $$DIR/awall.initial
mv $$DIR/awall.final $$DIR/awall
