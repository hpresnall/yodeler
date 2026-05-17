MOUNTPOINT=/media/usb/

umount "$$MOUNTPOINT"/proc
umount "$$MOUNTPOINT"/dev
umount "$$MOUNTPOINT"/sys

umount $$MOUNTPOINT