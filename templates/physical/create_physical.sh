# use site-level APK cache for this boot
# will be partially populated by Alpine install
log "Setting up APK cache for site '$SITE_NAME'"
rm -f /etc/apk/cache
mkdir -p $$SITE_DIR/apk_cache
ln -s $$(realpath $$SITE_DIR/apk_cache) /etc/apk/cache

# alpine install will setup the network
# block all incoming traffic until awall is configured
# install rsync too for later use; avoid issues with moving world file later
log "Blocking incoming network traffic"
apk -q add iptables ip6tables rsync
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -P INPUT DROP
ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# alpine install uses /etc/apk/world to configure the base system
# ensure apks needed for setup do not end up on the installed system unless required
cp /etc/apk/world /tmp

# install Alpine with answerfile
log -e "\nInstalling Alpine for '$HOSTNAME' to $SYSTEM_DEV"
setup-alpine -e -f $$DIR/answerfile > $$LOG 2>&1
log -e "Alpine install complete; starting yodeler configuration\n"

# copy back original world
cp /tmp/world /etc/apk

# mount the installed system and run setup inside of chroot
INSTALLED=/media/installed
log "Mounting installed system at $$INSTALLED"
mkdir -p "$$INSTALLED"
mount ${SYSTEM_DEV}${SYSTEM_PARTITION} "$$INSTALLED"

log "Copying yodeler scripts & apk_cache for site '$SITE_NAME' to $$INSTALLED/root/" 
# do not include logs dir as that will stop output for this script
rsync -r --exclude logs "$$SITE_DIR" "$$INSTALLED/root"

# still using Alpine installer's network configuration in chroot
# backup the installed resolv.conf, if any, and use the installer's instead
RESOLV_CONF_PATH="$$INSTALLED/root/$SITE_NAME/$HOSTNAME"
RESOLV_CONF=""
if [ -f "$$RESOLV_CONF_PATH/resolv.conf" ]; then
  RESOLV_CONF=resolv.conf
elif [ -f "$$RESOLV_CONF_PATH/resolv.conf.head" ]; then
  RESOLV_CONF=resolv.conf.head
fi
if [ -z "$$RESOLV_CONF" ]; then
  cp "$$RESOLV_CONF_PATH/$$RESOLV_CONF" "$$RESOLV_CONF_PATH/resolv.orig"
fi
cp /etc/resolv.conf "$$RESOLV_CONF_PATH/resolv.conf" # will be moved to /etc by setup.sh

# cache APKs on installed system in /root/$SITE_NAME
# note symlinks are relative to installed root fs
rm -f "$$INSTALLED/etc/apk/cache"
ln -s /root/$SITE_NAME/apk_cache "$$INSTALLED/etc/apk/cache"

# setup /tmp/envvars that will be copied into the installed system
mkdir -p /tmp/$HOSTNAME/tmp
rm -f /tmp/$HOSTNAME/tmp/envvars
touch /tmp/$HOSTNAME/tmp/envvars
# export START_TIME in chroot to use the same LOG_DIR this script is already using
echo "export START_TIME=$$START_TIME" >> /tmp/$HOSTNAME/tmp/envvars

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
# run the rest of the script even if setup.sh fails
trap - ERR
set +o errexit
# note running scripts _copied_ into the installed system
chroot "$$INSTALLED" /bin/sh -c "cd /root/$SITE_NAME/$HOSTNAME; ./setup.sh"
RESULT=$$?
trap exception ERR
set -o errexit

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
if [ -f "$$RESOLV_CONF_PATH/resolv.orig" ]; then
  mv "$$RESOLV_CONF_PATH/resolv.orig" "$$RESOLV_CONF_PATH/$$RESOLV_CONF"
  rm "$$INSTALLED/etc/resolv.conf"
  install -o root -g root -m 644 "$$RESOLV_CONF_PATH/$$RESOLV_CONF" "$$INSTALLED/etc"
fi

if [ "$$RESULT" == 0 ]; then
  log -e "\nSuccessful Yodel for '$HOSTNAME'!\nThe system will now reboot\n"
  # reboot
else
  log -e "\nUnsuccessful Yodel for '$HOSTNAME'; see $$LOG for details"
fi