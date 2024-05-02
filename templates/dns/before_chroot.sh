# before chroot, use the site build image to create a pi-hole like hosts file
# and a lua script pdns-recusor can use
log "Building blackhole hosts file"

cp "$$DIR/build_recursor_lua.sh" "$$SITE_BUILD_MOUNT/tmp"
cp "$$DIR/create_lua_blackhole.py" "$$SITE_BUILD_MOUNT/tmp"

chmod +x "$$SITE_BUILD_MOUNT/tmp/build_recursor_lua.sh"
chroot "$$SITE_BUILD_MOUNT" "/tmp/build_recursor_lua.sh"

# build puts lua script in build image's /tmp
# move to /tmp that will be inside the vm when running setup.sh
mkdir -p "/tmp/$HOSTNAME/tmp/"
mv "$$SITE_BUILD_MOUNT/tmp/blackhole.lua" "/tmp/$HOSTNAME/tmp/"