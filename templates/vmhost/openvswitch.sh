log "Configuring Open vSwitch"

rc-update add ovs-modules boot
rc-update add ovsdb-server boot
rc-update add ovs-vswitchd boot

echo tun >> /etc/modules

# directories must exist for OpenRC to start services
mkdir -p /run/openrc/started
mkdir -p /run/openrc/exclusive

# make it look like the system booted
# note still using network defined during Alpine install
echo default > /run/openrc/softlevel

# run now
# ovs-modules starts openvswitch kernel module; this was loaded loaded before running this script in chroot
rc-service ovsdb-server start
rc-service ovs-vswitchd start
