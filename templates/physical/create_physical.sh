# use site-level APK cache for this boot
# will be partially populated by Alpine install
log "Setting up APK cache for site '$SITE_NAME'"
rm -f /etc/apk/cache
mkdir -p $$SITE_DIR/apk_cache
ln -s $$(realpath $$SITE_DIR/apk_cache) /etc/apk/cache

# alpine install uses /etc/apk/world to configure the base system
# ensure iptables does end up on the installed system unless required
cp /etc/apk/world /tmp

# alpine install will setup the network
# block all incoming traffic until awall is configured
log "Blocking incoming network traffic"
apk -q add iptables
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# copy back original
cp /tmp/world /etc/apk

# install Alpine with answerfile
log -e "Installing Alpine to $ROOT_DEV\n"
# redirecting to allow confirmation of deleting existing partitions
setup-alpine -e -f $$DIR/answerfile >&3 2>&1
log -e "\nAlpine install complete"

# mount the installed system and run setup inside of chroot
log "Mounting installed system"
INSTALLED=/media/installed
mkdir -p "$$INSTALLED"
mount ${ROOT_DEV}${ROOT_PARTITION} "$$INSTALLED"

log "Copying yodeler scripts & apk_cache for site '$SITE_NAME' to $$INSTALLED/root/" 
apk -q add rsync
# do not include logs dir as that will stop output for this script
rsync -r --exclude logs "$$SITE_DIR" "$$INSTALLED/root"

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

# setup /tmp/envvars that will be copied into the installed system
mkdir -p /tmp/$HOSTNAME/tmp
rm -f /tmp/$HOSTNAME/tmp/envvars
touch /tmp/$HOSTNAME/tmp/envvars

$BEFORE_CHROOT

cp -r /tmp/$HOSTNAME/tmp/* "$$INSTALLED"/tmp

log "Chrooting to installed system"
mkdir -p "$$INSTALLED"/proc "$$INSTALLED"/dev "$$INSTALLED"/sys
mount -t proc none "$$INSTALLED"/proc
mount --bind /dev "$$INSTALLED"/dev
mount --make-private "$$INSTALLED"/dev
mount --bind /sys "$$INSTALLED"/sys
mount --make-private "$$INSTALLED"/sys

log -e "\nRunning setup for '$HOSTNAME' in chroot"
# continue running the rest of the script even if setup.sh fails
set +o errexit
# export START_TIME in chroot to use the same LOG_DIR this script is already using
chroot "$$INSTALLED" /bin/sh -c "export START_TIME=$$START_TIME; cd /root/$SITE_NAME/$HOSTNAME; ./setup.sh"
RESULT=$$?

# mount status gets reset sometimes; ensure still writable
mount -o remount,rw $$YODELER_DEV

log "Copying APK cache out of chroot"
# copy any new APKS back to the site APK cache, deleting old versions
rsync -r --delete "$$INSTALLED/root/$SITE_NAME/apk_cache" "$$SITE_DIR"

if [ -d "$$INSTALLED/root/$SITE_NAME/logs" ]; then
  log "Copying logs from chroot to '$$LOG_DIR'"
  rsync -r "$$INSTALLED/root/$SITE_NAME/logs" "$$SITE_DIR"
fi

# copy back final resolv.conf
if [ -f "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.orig" ]; then
  mv "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.orig" "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.conf"
  install -o root -g root -m 644 "$$INSTALLED/root/$SITE_NAME/$HOSTNAME/resolv.conf" "$$INSTALLED/etc"
fi

if [ "$$RESULT" == 0 ]; then
  log -e "\nSuccessful Yodel!\nThe system will now reboot\n"
  # reboot
else
  log "Installation did not complete successfully; please see $$LOG for more info"
fi
