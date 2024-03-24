# before chroot, use the site build image to 
# create a pi-hole like hosts file and a lua script pdns-recusor can use
log "Building blackhole hosts file"

BUILD_IMG="/media/${SITE_NAME}_build"

cp "$$DIR/build_recursor_lua.sh" "$$BUILD_IMG/tmp"
cp "$$DIR/create_lua_blackhole.py" "$$BUILD_IMG/tmp"

chmod +x "$$BUILD_IMG/tmp/build_recursor_lua.sh"
chroot "$$BUILD_IMG" "/tmp/build_recursor_lua.sh"

# build puts lua script in build image's /tmp
# move to /tmp that will be inside the vm when running setup.sh
mkdir -p "/tmp/$HOSTNAME/tmp/"
mv "$$BUILD_IMG/tmp/blackhole.lua" "/tmp/$HOSTNAME/tmp/"