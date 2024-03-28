log "Removing & de-installing kernel modules for vmhost"

if $$(grep vendor_id /proc/cpuinfo | head -n 1 | grep AMD > /dev/null); then
  modprobe -r kvm_amd
else
  modprobe -r kvm_intel
fi

modprobe -r tun
modprobe -r nbd
modprobe -r openvswitch

apk -q del openvswitch qemu-system-x86_64