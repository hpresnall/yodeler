#!/bin/sh
# hook script for kea-dhcp6 that adds or removes a route for prefix delegations as needed

add_route() {
  # add route for delegated prefix
  doas /sbin/ip -6 route replace $LEASE6_ADDRESS/$LEASE6_PREFIX_LEN via $QUERY6_REMOTE_ADDR dev $QUERY6_IFACE_NAME proto static
}

del_route() {
  # remove route for delegated prefix
  doas /sbin/ip -6 route delete $LEASE6_ADDRESS/$LEASE6_PREFIX_LEN proto static
}

# leases6_committed hook can contain multiple messages
# parse each LEASES6 and DELETED_LEASES6 group
if [ "$1" = "leases6_committed" ]; then
  if [ $LEASES6_SIZE -gt 0 ]; then
    i=0
    while [ $i -lt $LEASES6_SIZE ]; do
      eval type='$'LEASES6_AT${i}_TYPE # use eval to dynamically lookup variable names by index

      if [ "$type" = "IA_PD" ]; then
        eval LEASE6_ADDRESS='$'LEASES6_AT${i}_ADDRESS # e.g. LEASES6_AT0_ADDRESS
        eval LEASE6_PREFIX_LEN='$'LEASES6_AT${i}_PREFIX_LEN
        add_route
      fi

      i=$(($i + 1))
    done
  fi

  if [ $DELETED_LEASES6_SIZE -gt 0 ]; then
    i=0
    while [ $i -lt $DELETED_LEASES6_SIZE ]; do
      eval type='$'DELETED_LEASES6_AT${i}_TYPE

      if [ "${type}" = "IA_PD" ]; then
        eval LEASE6_ADDRESS='$'DELETED_LEASES6_AT${i}_ADDRESS
        eval LEASE6_PREFIX_LEN='$'DELETED_LEASES6_AT${i}_PREFIX_LEN
        del_route
      fi

      i=$(($i + 1))
    done
  fi

  exit
fi

# otherwise, handle hook based on value
if [ "$LEASE6_TYPE" != "IA_PD" ]; then
  exit
fi

case "$1" in
"lease6_renew")
  add_route
  ;;
"lease6_rebind")
  add_route
  ;;
"lease6_recover")
  add_route
  ;;
"lease6_expire")
  del_route
  ;;
"lease6_release")
  del_route
  ;;
"lease6_decline")
  del_route
  ;;
esac
