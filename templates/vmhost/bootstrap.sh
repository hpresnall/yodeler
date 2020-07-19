. $$DIR/install_alpine.sh

# assume / is the 3rd partition
echo "Mounting installed system"
INSTALL=/media/tmp
mkdir $$INSTALL
mount ${ROOT_DEV}3 $$INSTALL

echo "Copying yodeler scripts to $$INSTALL/root/"
cp -R $$DIR/../../yodeler $$INSTALL/root/

# cache APKs
# note symlinks are to installed root fs
mkdir $$INSTALL/root/apk_cache
ln -s /root/apk_cache $$INSTALL/etc/apk/cache

# place contents of apk_cache from previous install parallel to yodeler dir
# to avoid extra networking traffic on re-setup
if [ -d "$$DIR/../../../apk_cache" ]; then
  echo "Copying existing APK cache dir to installed system"
  cp -R $$DIR/../../../apk_cache $$INSTALL/root/apk_cache
fi

# run setup after reboot
ln -s /etc/init.d/local $$INSTALL/etc/runlevels/default/local
cp $$DIR/setup.start $$INSTALL/etc/local.d/
chmod +x $$INSTALL/etc/local.d/setup.start

echo "Base Alpine install complete!"
echo "The system will reboot multiple times to complete all required setup tasks"

reboot
