# Utility for creating manipulating IP addresses.

import ipaddress

# reverse pointers on subnets are currently broken; see https://github.com/python/cpython/pull/29011
# resort to text manipulation instead
def rptr_ipv4(subnet: ipaddress.IPv4Network):
    rptr = str(subnet.reverse_pointer)  # "0/24.251.16.172.in-addr.arpa"

    # drop leading subnet part
    prefix = "0/" + str(subnet.prefixlen) + "."

    return rptr[len(prefix):]


def hostpart_ipv4(address: ipaddress.IPv4Address):
    # last octet
    a = str(address)
    return a[a.rindex(".")+1:]


def rptr_ipv6(subnet: ipaddress.IPv6Network):
    # 0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.2.0.0.7.c.6.0.8.e.7.8.4.2.d.f.ip6.arpa
    addr = str(subnet.network_address.reverse_pointer)

    # remove leading 0's from reverse, one for each hex digit
    # note this _breaks_ for subnets not divisible by 4
    idx = int(subnet.prefixlen / 4) * 2  # 2 for 0.

    return addr[idx:]


def ipv6_hostpart(address: ipaddress.IPv6Address, prefixlen: int):
    # remove leading 0:'s from reverse, one for each hex digit
    # note this _breaks_ for subnets not divisible by 4
    idx = int(prefixlen / 4) * 2  # 2 for 0.

    return address.reverse_pointer[:idx-1]
