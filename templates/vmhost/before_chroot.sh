# vm host install needs openvswitch and kvm modules installed & running
# however, the installer's kernel version could be different than the installed system
# so, modprobe in chroot will not work; do it here instead
log "Installing & starting kernel modules for vmhost"
apk -q add openvswitch qemu-system-x86_64

modprobe openvswitch
modprobe nbd
modprobe tun

if $$(grep vendor_id /proc/cpuinfo | head -n 1 | grep AMD > /dev/null); then
  modprobe kvm_amd
else
  modprobe kvm_intel
fi