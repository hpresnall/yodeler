
  # create the virtual function
  echo $COUNT > /sys/class/net/$UPLINK/device/sriov_numvfs

$DISABLE_UPLINK_IPV6

  # parent interface must be up
  ip link set $UPLINK up

  # configure each virtual function(s)
  i=0
  while [ $$1 -lt $COUNT ]; do
    # interface corresponding to the vf
    vf=$$(ls -1 /sys/class/net/$UPLINK/device/virtfn$$i/net)

    # disable ipv6
$DISABLE_VF_IPV6

    i=$$(( $$i + 1 ))
  done