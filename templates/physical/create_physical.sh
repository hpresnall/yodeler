set -o errexit

# use site-level APK cache for this boot
# will be partially populated by Alpine install
echo "Setting up APK cache for site $SITE"
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

# assume the 3rd partition is root
echo "Mounting installed system"
INSTALLED=/media/installed
mkdir -p "$$INSTALLED"
mount ${ROOT_DEV}3 "$$INSTALLED"

echo "Copying yodeler scripts for site '$SITE' to $$INSTALLED/root/"
# note this includes the site-level apk_cache
cp -R $$DIR/../../$SITE "$$INSTALLED/root/"

# for setup.sh that needs the internet, use _this install's_ resolv.conf
if [ -f "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.conf" ]; then
  cp "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.conf" "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.orig"
fi
cp /etc/resolv.conf "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.conf" # will be moved to /etc by setup.sh

# cache APKs on installed system in /root
# note symlinks are relative to installed root fs
rm -f "$$INSTALLED/etc/apk/cache"
ln -s /root/$SITE/apk_cache "$$INSTALLED/etc/apk/cache"

echo "Chrooting to installed system"
mkdir -p "$$INSTALLED"/proc "$$INSTALLED"/dev "$$INSTALLED"/sys
mount -t proc none "$$INSTALLED"/proc
mount --bind /dev "$$INSTALLED"/dev
mount --make-private "$$INSTALLED"/dev
mount --bind /sys "$$INSTALLED"/sys
mount --make-private "$$INSTALLED"/sys

echo -n "Running setup for $HOSTNAME"
set +o errexit # copy APKs even if setup fails
chroot "$$INSTALLED" /bin/sh -c "cd /root/$SITE/$HOSTNAME && ./setup.sh"
RESULT=$$?
echo "Complete"

echo "Synching $HOSTNAME's APK cache back to site-level cache"
# copy any new APKS back to the site APK cache
apk -q add rsync
rsync -r "$$INSTALLED/root/$SITE/apk_cache" $$DIR/../

# copy back final resolv.conf
if [ -f "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.orig" ]; then
  mv "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.orig" "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.conf"
  install -o root -g root -m 644 "$$INSTALLED/root/$SITE/$HOSTNAME/resolv.conf" "$$INSTALLED/etc"
fi

if [ "$$RESULT" == "0" ]; then
  echo "Successful Yodel!"
  echo "The system will now reboot""
  # reboot
else
  echo "Installation did not complete successfully; please see the logs for more info"  
fi
