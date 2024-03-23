# before chroot, use the site build image to create a pi-hole like hosts file
log "Building blackhole hosts file"
BUILD_IMG="/media/${SITE_NAME}_build"
cp "$$DIR/build_hosts.sh" "$$BUILD_IMG/tmp"
chmod +x "$$BUILD_IMG/tmp/build_hosts.sh"
chroot "$$BUILD_IMG" "/tmp/build_hosts.sh"
# script puts hosts in chrooted /tmp; move to /tmp that will be inside the vm for setup.sh
mv "$$BUILD_IMG/tmp/hosts" "/tmp/$HOSTNAME/tmp/"