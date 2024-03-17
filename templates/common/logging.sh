# configure logging
if [ -z $$START_TIME ]; then
  START_TIME=$$(date +"%Y%m%d_%H%M%S")
fi

LOG_DIR=$$SITE_DIR/logs/$$START_TIME
mkdir -p "$$LOG_DIR"
LOG=$$LOG_DIR/$HOSTNAME.log

if [ -t 4 ]; then
  # for chroot and subshells, continue using parent's stdout at fd 4
  :
else
  exec 4>&1 # the outermost console
fi

# fd 3 writes to logfile & console
exec 3> >(tee -a $$LOG >&4)

echo "Writing logs to $$LOG"
# stdout & stderr to log
exec 1>> $$LOG
exec 2>&1

trap 'exec 3>&-;exec 1>&-' EXIT
