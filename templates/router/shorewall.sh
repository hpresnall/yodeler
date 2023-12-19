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

# setup ulogd
install -o root -g root -m 600 $$DIR/ulogd.conf /etc/
install -o root -g root -m 644 $$DIR/logrotate-firewall /etc/logrotate.d/firewall
mkdir -p /var/log/firewall
chown root:wheel /var/log/firewall
chmod 640 /var/log/firewall

rc-update add shorewall boot
rc-update add shorewall6 boot
rc-update add ulogd boot
