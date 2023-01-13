# ensure the drive running this script is writable
mount -o remount,rw $$(realpath $$(df . | grep '^/' | cut -d' ' -f1))

# use site-level APK cache for this boot
# will be partially populated by Alpine install
echo "Setting up APK cache for site '$SITE_NAME'"
rm -f /etc/apk/cache
mkdir -p $$DIR/../apk_cache
ln -s $$(realpath $$DIR/../apk_cache) /etc/apk/cache

# alpine install will setup the network
# block all incoming traffic until awall is configured
echo "Blocking incoming traffic before installation"
apk -q add iptables
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# install Alpine with answerfile
echo -n "Installing Alpine to $ROOT_DEV"
# TODO log install output somewhere
setup-alpine -e -f $$DIR/answerfile
echo
echo "Alpine install complete"

# mount the installed system and run setup inside of chroot
echo "Mounting installed system"
INSTALLED=/media/installed
mkdir -p "$$INSTALLED"
mount ${ROOT_DEV}${ROOT_PARTITION} "$$INSTALLED"

# TODO this is only needed for vmhost; need a method to add to this script based on role

echo "Copying yodeler scripts for site '$SITE_NAME' to $$INSTALLED/root/"
# note this includes the site-level apk_cache
cp -R $$DIR/../../$SITE_NAME "$$INSTALLED/root/"

# vm host install need openvswitch module running
# however, the installer's kernel version could be different than the installed system
# so, modprobe in chroot will not work; do it here instead
# TODO need check for intel / amd
# TODO remove this for non-vmhost physical servers
setup-apkrepos -1 -c
apk -q add openvswitch qemu-system-x86_64
modprobe openvswitch
modprobe nbd
modprobe tun
modprobe kvm_intel

# still using Alpine installer's network configuration in chroot
# backup the installed resolv.conf and use the current installation's instead
if [ -f "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.conf" ]; then
  cp "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.conf" "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.orig"
fi
cp /etc/resolv.conf "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.conf" # will be moved to /etc by setup.sh

# cache APKs on installed system in /root/$SITE_NAME
# note symlinks are relative to installed root fs
rm -f "$$INSTALLED/etc/apk/cache"
ln -s /root/$SITE_NAME/apk_cache "$$INSTALLED/etc/apk/cache"

echo "Chrooting to installed system"
mkdir -p "$$INSTALLED"/proc "$$INSTALLED"/dev "$$INSTALLED"/sys
mount -t proc none "$$INSTALLED"/proc
mount --bind /dev "$$INSTALLED"/dev
mount --make-private "$$INSTALLED"/dev
mount --bind /sys "$$INSTALLED"/sys
mount --make-private "$$INSTALLED"/sys

echo "Running setup for '$HOSTNAME' inside chroot"
set +o errexit # copy cached APKs even if setup fails
chroot "$$INSTALLED" /bin/sh -c "cd /root/$SITE_NAME/$HOSTNAME && ./setup.sh"
RESULT=$$?

echo "Synching $HOSTNAME's APK cache back to site-level cache"
# copy any new APKS back to the site APK cache
apk -q add rsync
rsync -r "$$INSTALLED/root/$SITE_NAME/apk_cache" $$DIR/../

# copy back final resolv.conf
if [ -f "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.orig" ]; then
  mv "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.orig" "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.conf"
  install -o root -g root -m 644 "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.conf" "$$INSTALLED/etc"
fi

if [ "$$RESULT" == 0 ]; then
  echo "Successful Yodel!"
  echo "The system will now reboot"
  # reboot
else
  echo "Installation did not complete successfully; please see the logs for more info"
fi
