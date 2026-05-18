if [ "$$(virsh domstate $HOSTNAME)" == "running" ]; then
    echo "cannot mount VM disk image when $HOSTNAME is running"
    exit 1
fi

MOUNTPOINT=/media/usb

# loop mount the VM disk image
mount -o loop $VM_IMAGES_PATH/$HOSTNAME.img $$MOUNTPOINT

# mount kernel filesystems so things like apk upgrade work
mkdir -p "$$MOUNTPOINT"/proc "$$MOUNTPOINT"/dev "$$MOUNTPOINT"/sys
mount -t proc none "$$MOUNTPOINT"/proc
mount --bind /dev "$$MOUNTPOINT"/dev
mount --make-private "$$MOUNTPOINT"/dev
mount --bind /sys "$$MOUNTPOINT"/sys
mount --make-private "$$MOUNTPOINT"/sys

chroot $$MOUNTPOINT