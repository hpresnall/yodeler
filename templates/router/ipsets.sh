# shorewall can use and save ipsets, but cannot create
IPSETS_4=/var/lib/shorewall/ipsets.save
touch $IPSETS_4
chown root:root $IPSETS_4
chmod 600 $IPSETS_4

IPSETS_6=/var/lib/shorewall6/ipsets.save
touch $IPSETS_6
chown root:root $IPSETS_6
chmod 600 $IPSETS_6

# default set of banned ips
echo "create banned hash:ip family inet hashsize 2048 maxelem 16384" > $IPSETS_4
echo "create banned6 hash:ip family inet6 hashsize 2048 maxelem 16384" > $IPSETS_6
