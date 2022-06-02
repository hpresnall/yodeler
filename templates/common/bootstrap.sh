set -o errexit

# use site-level APK cache for this boot
rm -f /etc/apk/cache
ln -s $$DIR/../apk_cache /etc/apk/cache

#echo iptables >> /etc/apk/world
#apk add

. $$DIR/install_alpine.sh

# assume / is the 3rd partition
echo "Mounting installed system"
INSTALLED=/media/installed
mkdir -p $$INSTALLED
mount ${ROOT_DEV}3 $$INSTALLED

echo "Copying yodeler scripts for site '$SITE'  to $$INSTALLED/root/"
cp -R $$DIR/../$SITE $$INSTALLED/root/

# cache APKs on installed system in /root
# note symlinks are relative to installed root fs
mkdir -p $$INSTALLED/root/apk_cache
rm -f $$INSTALLED/etc/apk/cache
ln -s /root/apk_cache $$INSTALLED/etc/apk/cache

# place contents of APK cache from previous installs parallel to yodeler dir
# to avoid extra networking traffic on re-setup
if [ -d "$$DIR/../apk_cache" ]; then
  echo "Copying existing APK cache dir to installed system"
  cp -R $$DIR/../apk_cache/* $$INSTALLED/root/apk_cache
fi

# run setup after reboot
ln -s /etc/init.d/local $$INSTALLED/etc/runlevels/default/local
#cp $$DIR/setup.start $$INSTALLED/etc/local.d/
#chmod +x $$INSTALLED/etc/local.d/setup.start

echo "Base Alpine install complete!"
#echo "The system will now reboot to complete all required setup tasks"

echo "Chrooting to installed system"
mkdir -p "$$INSTALLED"/proc "$$INSTALLED"/dev "$$INSTALLED"/sys
mount -t proc none "$$INSTALLED"/proc
mount --bind /dev "$$INSTALLED"/dev
mount --make-private "$$INSTALLED"/dev
mount --bind /sys "$$INSTALLED"/sys
mount --make-private "$$INSTALLED"/sys

chroot $$INSTALLED

# make it look like the system booted and networking has started
# note still using network defined during Alpine install
mkdir -p /run/openrc/started
echo default > /run/openrc/softlevel
ln -s /etc/init.d/networking /var/run/openrc/started/networking

#mv /usr/lib/libvirt/storage-backend/libvirt_storage_backend_rbd.so /tmp

cd /root/yodeler/$HOSTNAME

. ./setup.sh

#reboot
