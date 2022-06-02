set -o errexit

# use site-level APK cache for this boot
# will be partially populated by Alpine install
rm -f /etc/apk/cache
mkdir -p $$DIR/../apk_cache
ln -s $$(realpath $$DIR/../apk_cache) /etc/apk/cache

#echo iptables >> /etc/apk/world
#apk add

. $$DIR/install_alpine.sh

# assume / is the 3rd partition
echo "Mounting installed system"
INSTALLED=/media/installed
mkdir -p $$INSTALLED
mount ${ROOT_DEV}3 $$INSTALLED

echo "Copying yodeler scripts for site '$SITE' to $$INSTALLED/root/"
# note this includes the site-level apk_cache
cp -R $$DIR/../../$SITE $$INSTALLED/root/

# for scripts that need internet, use this install's resolv.conf, not the final one
# TODO better way to handle this
cp /etc/resolv.conf $$INSTALLED/root/$SITE/$HOSTNAME/resolv.orig

# cache APKs on installed system in /root
# note symlinks are relative to installed root fs
rm -f $$INSTALLED/etc/apk/cache
ln -s /root/$SITE/apk_cache $$INSTALLED/etc/apk/cache

echo "Base Alpine install complete!"

echo "Chrooting to installed system"
mkdir -p "$$INSTALLED"/proc "$$INSTALLED"/dev "$$INSTALLED"/sys
mount -t proc none "$$INSTALLED"/proc
mount --bind /dev "$$INSTALLED"/dev
mount --make-private "$$INSTALLED"/dev
mount --bind /sys "$$INSTALLED"/sys
mount --make-private "$$INSTALLED"/sys

set +o errexit # copy APKs even if setup fails
chroot $$INSTALLED /bin/sh -c "cd /root/$SITE/$HOSTNAME && ./setup.sh"
RESULT=$?

# copy any new APKS back to the site APK cache
cp -r $$INSTALLED/root/$SITE/apk_cache $$DIR/../apk_cache

if [ "$RESULT" == "0" ]; then
  echo "The system will now reboot to complete all required setup tasks"
  #reboot
else
  echo "Installation did not complete successfully; please see the logs for more info"
fi
