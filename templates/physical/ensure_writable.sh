# ensure the drive running this script is writable
YODELER_DEV=$$(df $$DIR | grep -E '^(/|share)' | cut -d' ' -f1)

# share when testing in VM with shared host filesystem
if [ "$$YODELER_DEV" != "share" ]; then
  YODELER_DEV=$$(realpath $$YODELER_DEV)
  mount -o remount,rw $$YODELER_DEV
fi
