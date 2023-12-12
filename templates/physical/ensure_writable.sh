# ensure the drive running this script is writable
YODELER_DEV=$$(df $$DIR | grep -E '^(/|share)' | cut -d' ' -f1)

# ensure yodeler is running from a read-write filesystem
# alpine defaults to readonly for the boot disk of live install
# skip if testing on a VM where yodeler is on a shared host filesystem
if [ "$$YODELER_DEV" != "share" -a "$$YODELER_DEV" != "shared" ]; then
  YODELER_DEV=$$(realpath $$YODELER_DEV)
  mount -o remount,rw $$YODELER_DEV
fi
