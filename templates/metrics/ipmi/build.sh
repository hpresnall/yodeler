# using the site build image, download the IPMI exporter, if needed
$$SITE_DIR/$VMHOST/create_build_image.sh

if [ -d "$$SITE_BUILD_IMG/build/ipmi_exporter-1.8.0.linux-amd64" ]; then
  log "Using already downloaded Prometheus IMPI collector"
else
  log "Downloading the Prometheus IPMI collector"
  cd $$SITE_BUILD_IMG/build
  apk -q --no-progress add wget
  wget -q https://github.com/prometheus-community/ipmi_exporter/releases/download/v1.8.0/ipmi_exporter-1.8.0.linux-amd64.tar.gz
  tar zxf ipmi_exporter-1.8.0.linux-amd64.tar.gz
  rm ipmi_exporter-1.8.0.linux-amd64.tar.gz
  cd - > /dev/null 2>&1
fi

# copy IPMI exporter /tmp for use in setup.sh
mkdir -p "/tmp/$HOSTNAME/tmp/"
cp "$$SITE_BUILD_IMG/build/ipmi_exporter-1.8.0.linux-amd64/ipmi_exporter" "/tmp/$HOSTNAME/tmp/ipmi-exporter"
