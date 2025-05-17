
  # create the virtual function(s) needed by VMs using parent interface $UPLINK
  echo $COUNT > /sys/class/net/$UPLINK/device/sriov_numvfs

  # disable ipv6 on the parent interface
$DISABLE_UPLINK_IPV6

  # parent interface must be up
  ip link set $UPLINK up

  # disable ipv6 on each virtual function
  # this does not disable ipv6 in the VM
  i=0
  while [ $$1 -lt $COUNT ]; do
    # interface corresponding to the vf
    vf=$$(ls -1 /sys/class/net/$UPLINK/device/virtfn$$i/net)

$DISABLE_VF_IPV6

    i=$$(( $$i + 1 ))
  done