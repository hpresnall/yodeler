# create and populate /backup from the site backup
mkdir /backup
chown root:root /backup
chmod 750 /backup

if [ -d $$SITE_DIR/backup/$HOSTNAME ]; then
  log "Copying site backup to /backup"
  cp -r $$SITE_DIR/backup/$HOSTNAME/* /backup
  # note $$SITE_DIR/backup/$HOSTNAME still exists but will not be current!
fi
