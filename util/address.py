# Utility for creating and manipulating IP addresses.

import ipaddress


def rptr_ipv4(subnet: ipaddress.IPv4Network) -> str:
    # reverse pointers on subnets are currently broken; see https://github.com/python/cpython/pull/29011
    # resort to text manipulation instead
    rptr = str(subnet.reverse_pointer)  # "0/24.251.16.172.in-addr.arpa"

    # drop leading subnet part
    prefix = "0/" + str(subnet.prefixlen) + "."

    return rptr[len(prefix):]


def hostpart_ipv4(address: ipaddress.IPv4Address):
    # last octet
    a = str(address)
    return a[a.rindex(".")+1:]


def rptr_ipv6(subnet: ipaddress.IPv6Network) -> str:
    # 0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.2.0.0.7.c.6.0.8.e.7.8.4.2.d.f.ip6.arpa
    addr = str(subnet.network_address.reverse_pointer)

    # remove leading 0's from reverse, one for each hex digit
    # note this _breaks_ for subnets not divisible by 4
    idx = int(subnet.prefixlen / 4) * 2  # 2 for 0.

    return addr[idx:]


def ipv6_hostpart(address: ipaddress.IPv6Address, prefixlen: int) -> str:
    # remove leading 0:'s from reverse, one for each hex digit
    # note this _breaks_ for subnets not divisible by 4
    idx = int(prefixlen / 4) * 2  # 2 for 0.

    return address.reverse_pointer[:idx-1]


def check_addresses(addresses: list[str | ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network]) -> tuple[int, bool]:
    version = 0
    is_networks = None

    for a in addresses:
        if isinstance(a, str):
            if '/' in a:  # assume CIDR
                a = ipaddress.ip_network(a)
            else:
                a = ipaddress.ip_address(a)

        if version:
            if a.version != version:
                raise ValueError("all IP versions must match")
        else:
            version = a.version

        current_network = (isinstance(a, ipaddress.IPv4Network) or isinstance(
            a, ipaddress.IPv6Network)) and (a.prefixlen != a.max_prefixlen)

        if is_networks is None:
            is_networks = current_network
        else:
            if is_networks != current_network:
                raise ValueError("IPs must be either all addresses or all networks")
            else:
                is_networks = is_networks or current_network

    if not is_networks:
        is_networks = False

    return (version, is_networks)
