"""Configuration & setup for a BIND9 DNS server."""
import os
import os.path

import util.shell
import util.file

from roles.role import Role


class Dns(Role):
    """Dns defines the configuration needed to setup BIND9 DNS."""

    def __init__(self):
        super().__init__("dns")

    def additional_packages(self):
        return {"bind", "bind-tools"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        if len(cfg["external_dns"]) == 0:
            raise KeyError("cannot configure DNS server with no external_dns addresses defined")

        domain = cfg["primary_domain"]
        if domain == "":
            domain = cfg["domain"]
            if domain == "":
                raise KeyError(("cannot configure DNS server "
                                "with no primary_domain or top-level site domain"))
        cfg["dns_domain"] = domain

        # force resolution to local nameserver
        # add all vlan domains to search
        resolv = ["nameserver 127.0.0.1", "nameserver ::1"]
        domains = []

        named = _init_named(cfg)

        zone_dir = os.path.join(output_dir, "zones")
        os.mkdir(zone_dir)

        # note walking interfaces, then vlans in the interface's vswitch
        # if an interface is not defined for a vswitch, its vlans
        #  _will not_ be able to resolve DNS queries unless the router routes DNS queries correctly
        for iface in cfg["interfaces"]:
            if iface["ipv4_address"] == "dhcp":
                raise KeyError("cannot configure DNS server with a DHCP ipv4 address")

            named["listen"].append(str(iface["ipv4_address"]))
            if iface["ipv6_address"] is not None:
                named["listen6"].append(str(iface["ipv6_address"]))

            for vlan in iface["vswitch"]["vlans"]:
                # no domain => no dns
                if vlan["domain"] == "":
                    continue

                domains.append(vlan["domain"])

                named["query_acl"].append(str(vlan["ipv4_subnet"]))
                if vlan["ipv6_subnet"] is not None:
                    named["query_acl6"].append(str(vlan["ipv6_subnet"]))

                if vlan["allow_dns_update"]:
                    named["update_acl"].append(str(vlan["ipv4_subnet"]))

                    if vlan["ipv6_subnet"] is not None:
                        named["update_acl6"].append(str(vlan["ipv6_subnet"]))

                _configure_zones(cfg, vlan, named, zone_dir)

        if cfg["domain"] != "":
            # top level domain last in search order
            domains.append(cfg["domain"])
            _configure_tld(cfg, named, zone_dir)

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
    named["query_acl"] = ["127.0.0.1/32"]
    named["query_acl6"] = ["::1/128"]
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
    named["query_acl"] = "\n".join(["\t" + val + ";" for val in named["query_acl"]])
    named["query_acl6"] = "\n".join(["\t" + val + ";" for val in named["query_acl6"]])
    named["update_acl"] = "\n".join(["\t" + val + ";" for val in named["update_acl"]])
    named["update_acl6"] = "\n".join(["\t" + val + ";" for val in named["update_acl6"]])


def _configure_zones(cfg, vlan, named, zone_dir):
    address = vlan["ipv4_subnet"].network_address
    reverse = address.reverse_pointer

    zone_name = vlan["domain"]
    zone_file_name = zone_name + ".zone"
    named["zones"].append(_zone_config(zone_name, zone_file_name))

    # note one forward zone
    # but, separate reverse zones for ipv4 and ipv6
    _forward_zone_file(zone_name, cfg["dns_domain"], vlan, zone_file_name, zone_dir)

    reverse_zone_name = _ipv4_reverse_zone_name(vlan)
    # drop in-addr.arpa from end
    reverse_zone_file_name = reverse_zone_name[:-13] + ".zone"
    named["reverse_zones"].append(_zone_config(reverse_zone_name, reverse_zone_file_name))

    zone_file = [_ZONE_TEMPLATE.format(reverse_zone_name, cfg["dns_domain"])]

    data = {"domain": vlan["domain"]}
    for host in vlan["hosts"]:
        if host["ipv4_address"] == "dhcp":
            continue
        data["hostname"] = host["hostname"]
        rptr = host["ipv4_address"].reverse_pointer
        data["reverse"] = rptr[:rptr.index(".")]
        zone_file.append(_PTR.format_map(data))

    zone_file.append("")  # ensure file ends with blank line

    util.file.write(reverse_zone_file_name, "\n".join(zone_file), zone_dir)

    if vlan["ipv6_subnet"] is not None:
        address = vlan["ipv6_subnet"].network_address
        reverse = address.reverse_pointer

        # remove leading 0:'s from reverse, one for each hex digit
        # note this _breaks_ for subnets not divisible by 4
        idx = int(vlan["ipv6_subnet"].prefixlen / 4) * 2
        reverse_zone_name = reverse[idx:]
        # use _ instead of : for filenames; remove trailing ::
        # [::-1] to reverse string
        reverse_zone_file_name = str(address).replace(":", "_").rstrip("_")[::-1] + ".zone"
        named["reverse_zones6"].append(_zone_config(reverse_zone_name, reverse_zone_file_name))

        zone_file = [_ZONE_TEMPLATE.format(reverse_zone_name, cfg["dns_domain"])]

        for host in vlan["hosts"]:
            if host["ipv6_address"] is None:
                continue
            data["hostname"] = host["hostname"]
            data["reverse"] = host["ipv6_address"].reverse_pointer[:idx-1]
            zone_file.append(_PTR.format_map(data))
        zone_file.append("")  # ensure file ends with blank line

        util.file.write(reverse_zone_file_name, "\n".join(zone_file), zone_dir)


def _zone_config(zone_name, zone_file, forward=False):
    zone = """zone "{0}" IN {{
	type master;
	file "{1}";
"""

    # by default, do not forward internal names by removing all forwarders
    if not forward:
        zone += "\tforwarders {{}};\n"

    zone += "}};\n"

    return zone.format(zone_name, zone_file)


def _forward_zone_file(zone_name, dns_domain, vlan, zone_file_name, zone_dir):
    zone_file = [_ZONE_TEMPLATE.format(zone_name, dns_domain)]
    cnames = [""]

    for host in vlan["hosts"]:
        if host["ipv4_address"] is not None:
            zone_file.append(_A.format_map(host))
        if host["ipv6_address"] is not None:
            zone_file.append(_AAAA.format_map(host))

        data = {"fqdn": host["hostname"] + "." + vlan["domain"]}
        for alias in host["aliases"]:
            if alias == host["hostname"]:
                continue  # no need for a CNAME if the hostname already matches
            data["alias"] = alias
            cnames.append(_CNAME.format_map(data))

    zone_file.extend(cnames)
    zone_file.append("")  # ensure file ends with blank line

    util.file.write(zone_file_name, "\n".join(zone_file), zone_dir)


def _configure_tld(cfg, named, zone_dir):
    # forward top level DNS queries; assume these are configured by the registrar
    # this is the first zone
    named["zones"].insert(0, _zone_config(cfg["domain"], cfg["domain"] + ".zone", True))

    zone_file = [_ZONE_TEMPLATE.format(cfg["domain"], cfg["dns_domain"])]
    for role, fqdn in cfg["roles_to_hostnames"].items():
        zone_file.append(_CNAME.format_map({"alias": role, "fqdn": fqdn}))
    zone_file.append("")  # ensure file ends with blank line

    util.file.write(cfg["domain"] + ".zone", "\n".join(zone_file), zone_dir)
    # no reverse zone needed since requests will be forwarded


def _ipv4_reverse_zone_name(vlan):
    parts = vlan["ipv4_subnet"].network_address.reverse_pointer.split(".")
    length = vlan["ipv4_subnet"].prefixlen

    # drop leading 0s based on prefixlen
    if length == 8:
        return ".".join(parts[3:])
    elif length == 16:
        return ".".join(parts[2:])
    elif length == 24:
        return ".".join(parts[1:])
    else:
        raise Exception(f"invalid subnet {vlan['ipv4_subnet']} for vlan {vlan['id']}")

    # remove leading 0. from reverse, one for each octet
    # note this _breaks_ for subnets other than 32, 24, 16 and 8, but
    # bind would need subzones for that anyway
    return int((32 - vlan["ipv4_subnet"].prefixlen) / 8) * 2


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

_A = "{hostname}\tIN\tA\t{ipv4_address}"
_AAAA = "{hostname}\tIN\tAAAA\t{ipv6_address}"
_CNAME = "{alias}\tIN\tCNAME\t{fqdn}."
_PTR = "{reverse}\tIN\tPTR\t{hostname}.{domain}."
