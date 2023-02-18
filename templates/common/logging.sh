# configure logging
if [ -z $$START_TIME ]; then
  START_TIME=$$(date +"%Y%m%d_%H%M%S")
fi

LOG_DIR=$$SITE_DIR/logs/$$START_TIME
mkdir -p  "$$LOG_DIR"
LOG=$$LOG_DIR/$HOSTNAME

if [ -t 3 ]; then
  # for chroot and subshells, continue using parent's stdout at fd 3
  :
else
  exec 3>&1
fi

echo "Writing logs to $$LOG" >&3
exec 1> $$LOG
exec 2>&1
