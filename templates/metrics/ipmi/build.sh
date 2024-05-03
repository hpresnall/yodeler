if [ -d "$SITE_BUILD_MOUNT/build/ipmi_exporter-1.8.0.linux-amd64" ]; then
  log "Using already downloaded Prometheus IPMI collector"
else
  # no need to chroot into build image since this only downloads a file
  log "Downloading the Prometheus IPMI collector"
  cd $SITE_BUILD_MOUNT/build
  apk -q --no-progress add wget
  wget -q https://github.com/prometheus-community/ipmi_exporter/releases/download/v1.8.0/ipmi_exporter-1.8.0.linux-amd64.tar.gz
  tar zxf ipmi_exporter-1.8.0.linux-amd64.tar.gz
  rm ipmi_exporter-1.8.0.linux-amd64.tar.gz
  cd - > /dev/null 2>&1
fi

cp "$SITE_BUILD_MOUNT/build/ipmi_exporter-1.8.0.linux-amd64/ipmi_exporter" "$SETUP_TMP/ipmi-exporter"
