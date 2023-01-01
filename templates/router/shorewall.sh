# remove all non-comment lines from default Shorewall configuration
# then add site configuration
for f in $$(ls -1 $$DIR/shorewall); do
  sed -i -n -E '/#|\?FORMAT/p' /etc/shorewall/$$f
  cat $$DIR/shorewall/$$f >> /etc/shorewall/$$f
done
for f in $$(ls -1 $$DIR/shorewall6); do
  sed -i -n -E '/#|\?FORMAT/p' /etc/shorewall6/$$f
  cat $$DIR/shorewall6/$$f >> /etc/shorewall6/$$f
done

sed -i -E 's/(STARTUP_ENABLED=)No/\1Yes/' /etc/shorewall/shorewall.conf
sed -i -E 's/(LOG_LEVEL=)info/\1NFLOG(4,0,1)/' /etc/shorewall/shorewall.conf
sed -i -E 's/(IP_FORWARDING=)Keep/\1Yes/' /etc/shorewall/shorewall.conf
sed -i -E 's/(SAVE_IPSETS=)No/\1Yes/' /etc/shorewall/shorewall.conf
sed -i -E 's/(USE_NFLOG_SIZE=)No/\1Yes/' /etc/shorewall/shorewall.conf

sed -i -E 's/(STARTUP_ENABLED=)No/\1Yes/' /etc/shorewall6/shorewall6.conf
sed -i -E 's/(LOG_LEVEL=)info/\1NFLOG(6,0,1)/' /etc/shorewall6/shorewall6.conf
sed -i -E 's/(IP_FORWARDING=)Keep/\1Yes/' /etc/shorewall6/shorewall6.conf
sed -i -E 's/(SAVE_IPSETS=)No/\1Yes/' /etc/shorewall6/shorewall6.conf
sed -i -E 's/(USE_NFLOG_SIZE=)No/\1Yes/' /etc/shorewall6/shorewall6.conf

# shorewall can use and save ipsets, but cannot create
BANNED="create banned hash:ip family inet hashsize 1024 maxelem 65536"
echo "$$BANNED" > /var/lib/shorewall/ipsets.save
chown root:root /var/lib/shorewall/ipsets.save
chmod 600 /var/lib/shorewall/ipsets.save
ipset $$BANNED

# setup ulogd
install -o root -g root -m 600 $$DIR/ulogd.conf /etc/
install -o root -g root -m 600 $$DIR/ulogd /etc/logrotate.d/
mkdir -p /var/log/firewall
chown root:wheel /var/log/firewall
chmod 640 /var/log/firewall

# configure dhcrelay and add IPv6 service
# TODO add all vlan interfaces; remove upper iface from dhcrelay6 config
echo 'IFACE="eth1.10 eth1.20"' >> /etc/conf.d/dhcrelay
cp /etc/conf.d/dhcrelay /etc/conf.d/dhcrelay6
echo 'DHCRELAY_OPTS="-6"' >> /etc/conf.d/dhcrelay6
sed -e "s/-i/-l/g" -e "s/dhcrelay/dhcrelay6/g" -e "s|sbin/dhcrelay6|sbin/dhcrelay|g" /etc/init.d/dhcrelay > /etc/init.d/dhcrelay6
chmod 755 /etc/init.d/dhcrelay6
# TODO determine ipv4 dhcp IPs
echo 'DHCRELAY_SERVERS="192.168.210.2"' >> /etc/conf.d/dhcrelay
echo 'DHCRELAY_SERVERS="-u fd24:87e8:06c7:10::2%eth1.10"' >> /etc/conf.d/dhcrelay6

rootinstall radvd.conf /etc

rc-update add shorewall boot
rc-update add shorewall6 boot
rc-update add ulogd boot

rc-update add dhcrelay default
rc-update add dhcrelay6 default

rc-update add radvd boot
