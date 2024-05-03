# use the site build image to create a pihole-like blackhole lua script pdns-recusor can use
log "Building blackhole hosts file"

cp "$$DIR/build_recursor_lua.sh" "$$SITE_BUILD_MOUNT/tmp"
cp "$$DIR/create_lua_blackhole.py" "$$SITE_BUILD_MOUNT/tmp"

chmod +x "$$SITE_BUILD_MOUNT/tmp/build_recursor_lua.sh"
# build while chrooted
chroot "$$SITE_BUILD_MOUNT" "/tmp/build_recursor_lua.sh"

# build puts lua script in build image's /tmp; move into the host
mv "$$SITE_BUILD_MOUNT/tmp/blackhole.lua" "$$SETUP_TMP"
