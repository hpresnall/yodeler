# create dhrelay6 service
cp /etc/conf.d/dhcrelay /etc/conf.d/dhcrelay6
echo 'DHCRELAY_OPTS="-6"' >> /etc/conf.d/dhcrelay6
# change command line flags & service name; set program name back to just dhcrelay
sed -e "s/-i/-l/g" -e "s/dhcrelay/dhcrelay6/g" -e "s|sbin/dhcrelay6|sbin/dhcrelay|g" /etc/init.d/dhcrelay > /etc/init.d/dhcrelay6
chmod 755 /etc/init.d/dhcrelay6