# mount the installed Alpine system
# assume / is the 3rd partition
echo "mounting installed system"
INSTALL=/media/tmp
mkdir $$INSTALL
mount ${ROOT_DEV}3 $$INSTALL

CACHE=$$INSTALL$APK_CACHE
ARCH=$$CACHE/`cat /etc/apk/arch`
mkdir -p $$ARCH

REPOS="--repository http://dl-cdn.alpinelinux.org/alpine/edge/testing \
--repository http://dl-cdn.alpinelinux.org/alpine/latest-stable/community"

# download all required APKs so all systems can be configured without network access
echo "putting all required APKs in $$CACHE"
apk $$REPOS -q update
apk $$REPOS fetch -q -R --output $$ARCH `cat $$DIR/all_packages`

# create an unsigned index; will require apk --allow-untrusted
apk index -q -o $$ARCH/APKINDEX.tar.gz $$ARCH/*.apk