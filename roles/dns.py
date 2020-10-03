"""Configuration & setup for a BIND9 DNS server."""
import os
import os.path
import ipaddress

import util.shell
import util.file

from roles.role import Role


class Dns(Role):
    """Dns defines the configuration needed to setup BUND9 DNS."""

    def __init__(self):
        super().__init__("dns")

    def additional_packages(self):
        return {"bind", "bind-tools"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        # TODO require primary domain; use this for the dns server name in all zone files
        # TODO better zone functions
        # site domain first - needs to be special and mostly contain cname records based on roles
        # vlan zones should be a single function that takes the named conf and the vlan
        # then separate functions for forward and reverse zone config and zone file
        if len(cfg["external_dns"]) == 0:
            raise KeyError("cannot configure DNS server with no external_dns addresses defined")

        resolv = ["nameserver 127.0.0.1", "nameserver ::1"]
        domains = []

        named = _init_named(cfg)
        zone_dir = os.path.join(output_dir, "zones")
        os.mkdir(zone_dir)

        # note walking interfaces then vlans in the interface's vswitch
        # if an interface is not defined for a vswitch, its vlans
        #  _will not_ be able to resolve DNS queries unless the router allows DNS
        for iface in cfg["interfaces"]:
            if iface["ipv4_address"] == "dhcp":
                raise KeyError("cannot configure DNS server with a DHCP ipv4 address")

            named["listen"].append(str(iface["ipv4_address"]))
            if iface["ipv6_address"] is not None:
                named["listen6"].append(str(iface["ipv6_address"]))

            for vlan in iface["vswitch"]["vlans"]:
                if vlan["domain"] != "":
                    domains.append(vlan["domain"])

                    named["zones"].append(_create_zone(vlan["domain"], vlan, zone_dir))
                    named["reverse_zones"].append(
                        _create_reverse_zone(vlan["domain"], vlan["ipv4_subnet"], zone_dir))
                    if vlan["ipv6_subnet"] is not None:
                        named["reverse_zones6"].append(
                            _create_reverse_zone(vlan["domain"], vlan["ipv6_subnet"], zone_dir))

                named["internal_acl"].append(str(vlan["ipv4_subnet"]))
                named["internal_acl6"].append(str(vlan["ipv6_subnet"]))

                if vlan["allow_dns_update"]:
                    named["update_acl"].append(str(vlan["ipv4_subnet"]))

                    if vlan["ipv6_subnet"] is not None:
                        named["update_acl6"].append(str(vlan["ipv6_subnet"]))

        if cfg["domain"] != "":
            # top level domain last in search order
            domains.append(cfg["domain"])

            # allow forwarding of top level DNS queries; assume are configured by the registrar
            named["zones"].insert(0, _create_zone(cfg["domain"], None, zone_dir, True))
            # no reverse zone needed since requests will be forwarded

        _format_named(named)

        util.file.write("named.conf",
                        util.file.substitute("templates/dns/named.conf", named), output_dir)

        resolv.append("search " + " ".join(domains))
        util.file.write("resolv.conf", "\n".join(resolv), output_dir)

        shell = util.shell.ShellScript("named.sh")
        shell.append(util.file.read("templates/dns/named.sh"))
        shell.write_file(output_dir)

        return [shell.name]


def _init_named(cfg):
    # parameter substitutions for named.conf
    named = {}
    named["listen"] = ["127.0.0.1"]
    named["listen6"] = ["::1"]
    named["forwarders"] = cfg["external_dns"]
    named["zones"] = []
    named["reverse_zones"] = []
    named["reverse_zones6"] = []
    named["internal_acl"] = ["127.0.0.1/32"]
    named["internal_acl6"] = ["::1/128"]
    named["update_acl"] = ["127.0.0.1/32"]
    named["update_acl6"] = ["::1/128"]
    named["cache_size"] = "{:0.0f}".format(cfg["memory_mb"] / 4)

    return named


def _format_named(named):
    # format named params with tabs and end with ;
    named["listen"] = "\n".join(["\t\t" + val + ";" for val in named["listen"]])
    named["listen6"] = "\n".join(["\t\t" + val + ";" for val in named["listen6"]])
    named["forwarders"] = "\n".join(["\t\t" + val + ";" for val in named["forwarders"]])
    named["zones"] = "\n".join(named["zones"])
    named["reverse_zones"] = "\n".join(named["reverse_zones"])
    named["reverse_zones6"] = "\n".join(named["reverse_zones6"])
    named["internal_acl"] = "\n".join(["\t" + val + ";" for val in named["internal_acl"]])
    named["internal_acl6"] = "\n".join(["\t" + val + ";" for val in named["internal_acl6"]])
    named["update_acl"] = "\n".join(["\t" + val + ";" for val in named["update_acl"]])
    named["update_acl6"] = "\n".join(["\t" + val + ";" for val in named["update_acl6"]])


def _create_zone(name, vlan, zone_dir, forward=False):
    zone = """zone "{0}" IN {{
	type master;
	file "{0}.zone";
"""
    # by default, do not forward internal names
    if not forward:
        zone += "\tforwarders {{}};\n"

    zone += "}};"

    zone_file = [_ZONE_TEMPLATE.format(name, name)]
    # zone_file.append()
    util.file.write(name + ".zone", "\n".join(zone_file), zone_dir)

    return zone.format(name)


def _create_reverse_zone(domain, subnet, zone_dir):
    zone = """zone "{0}" IN {{
	type master;
	file "{1}.zone";
}};"""

    reverse = subnet.network_address.reverse_pointer

    if isinstance(subnet, ipaddress.IPv6Network):
        # remove leading 0. from reverse, one for each hex digit
        # note this _breaks_ for subnets not divisible by 4
        reverse = reverse[int(subnet.prefixlen / 4) * 2:]
        # use _ instead of : for filenames; remove trailing ::
        filename = str(subnet.network_address).replace(":", "_").rstrip("_")
    elif isinstance(subnet, ipaddress.IPv4Network):
        # remove leading 0. from reverse and trailing .0 from filename, one for each octet
        # note this _breaks_ for subnets other than 32, 24, 16 and 8
        idx = int((32 - subnet.prefixlen) / 8) * 2
        reverse = reverse[idx:]
        filename = str(subnet.network_address)[:-idx]
    else:
        raise KeyError("invalid IP address type {}".format(type(subnet)))

    util.file.write(filename + ".zone", _ZONE_TEMPLATE.format(reverse, domain), zone_dir)

    # note, only creating a single zone
    # make no effort to carve up fractional subnets (i.e. ipv4 /26 or ipv6 /62)
    # into multiple zones as required by BIND given reverse arpa naming conventions
    z = zone.format(reverse, filename)
    print(z)
    return z


_ZONE_TEMPLATE = """$ORIGIN {0}.
$TTL 1D

@	3600	IN	SOA	dns.{1}.	admin.{1}.	(
	1	; serial-number
	1D	; refresh
	1H	; retry
	1W	; expire
	1H	; min
	)

	IN	NS	dns.{1}.
"""
