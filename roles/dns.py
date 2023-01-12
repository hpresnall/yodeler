"""Configuration & setup for a BIND9 DNS server."""
import os
import os.path

import util.shell
import util.file
import util.address

from roles.role import Role


class Dns(Role):
    """Dns defines the configuration needed to setup BIND9 DNS."""

    def __init__(self):
        super().__init__("dns")

    def additional_packages(self, cfg):
        return {"bind", "bind-tools"}

    def additional_configuration(self, cfg):
        if len(cfg["external_dns"]) == 0:
            raise KeyError("cannot configure DNS server with no external_dns addresses defined")

        domain = cfg["domain"]
        if not domain:
            domain = cfg["primary_domain"]
            if not domain:
                raise KeyError(("cannot configure DNS server with no primary_domain or top-level site domain"))
        cfg["dns_domain"] = domain

        # add hostname information for DNS
        # each vlan will be a separate zone
        cfg["dns_entries_by_vlan"] = {}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""

        _create_dns_entries(cfg)

        # for resolv.conf, force resolution to local nameserver and add all vlan domains to search
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
                if not vlan["domain"]:
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

        if cfg["dns_domain"] not in domains:
            # top level domain last in search order
            domains.append(cfg["dns_domain"])
            _configure_tld(cfg, named, zone_dir)

        _format_named(named)
        util.file.write("named.conf", util.file.substitute("templates/dns/named.conf", named), output_dir)

        resolv.append("search " + " ".join(domains))
        util.file.write("resolv.conf", "\n".join(resolv), output_dir)

        shell = util.shell.ShellScript("named.sh")
        shell.append(util.file.read("templates/dns/named.sh"))
        shell.write_file(output_dir)

        return [shell.name]


def _create_dns_entries(cfg):
    # create dns entries for all hosts
    for host_cfg in cfg["hosts"].values():
        for iface in host_cfg["interfaces"]:
            vlan = iface["vlan"]

            # no domain name => no DNS
            if not vlan["domain"]:
                continue

            if vlan["name"] not in cfg["dns_entries_by_vlan"]:
                cfg["dns_entries_by_vlan"][vlan["name"]] = []

            cfg["dns_entries_by_vlan"][vlan["name"]].append({
                "hostname": host_cfg["hostname"],
                "ipv4_address": iface["ipv4_address"],
                "ipv6_address": iface["ipv6_address"],
                "aliases": [role.name for role in host_cfg["roles"] if role.name != "common"]})

    # manually add host entries for router interfaces since they are defined based on routable vlans
    router = cfg["roles_to_hostnames"]["router"][0]

    for vswitch in cfg["vswitches"].values():
        for vlan in vswitch["vlans"]:
            if (not vlan["routable"]) or (not vlan["domain"]):
                continue

            if vlan["name"] not in cfg["dns_entries_by_vlan"]:
                cfg["dns_entries_by_vlan"][vlan["name"]] = []

            cfg["dns_entries_by_vlan"][vlan["name"]].append({
                "hostname": router,
                "ipv4_address": vlan["ipv4_subnet"].network_address + 1,
                "ipv6_address": vlan["ipv6_subnet"].network_address + 1,
                "aliases": ["router"]})


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
    zone_name = vlan["domain"]
    zone_file_name = zone_name + ".zone"
    named["zones"].append(_zone_config(zone_name, zone_file_name))

    # note one forward zone
    # but, separate reverse zones for ipv4 and ipv6
    _forward_zone_file(cfg, zone_name, vlan, zone_file_name, zone_dir)

    reverse_zone_name = util.address.rptr_ipv4(vlan["ipv4_subnet"])
    reverse_zone_file_name = reverse_zone_name[:-13] + ".zone"  # drop in-addr.arpa from end
    named["reverse_zones"].append(_zone_config(reverse_zone_name, reverse_zone_file_name))

    zone_file = [_ZONE_TEMPLATE.format(reverse_zone_name, cfg["dns_domain"])]

    # add a PTR record for each host
    data = {"domain": vlan["domain"]}
    for host in cfg["dns_entries_by_vlan"][vlan["name"]]:
        if host["ipv4_address"] == "dhcp":
            continue
        data["hostname"] = host["hostname"]
        data["reverse"] = util.address.hostpart_ipv4(host["ipv4_address"])
        zone_file.append(_PTR.format_map(data))

    zone_file.append("")  # ensure file ends with blank line

    util.file.write(reverse_zone_file_name, "\n".join(zone_file), zone_dir)

    if vlan["ipv6_subnet"] is not None:
        reverse_zone_name = util.address.rptr_ipv6(vlan["ipv6_subnet"])
        # use _ instead of : for filenames; remove trailing ::
        # [::-1] to reverse string
        reverse_zone_file_name = str(vlan["ipv6_subnet"].network_address).replace(":", "_").rstrip("_")[::-1] + ".zone"
        named["reverse_zones6"].append(_zone_config(reverse_zone_name, reverse_zone_file_name))

        zone_file = [_ZONE_TEMPLATE.format(reverse_zone_name, cfg["dns_domain"])]

        # add a PTR record for each host
        for host in cfg["dns_entries_by_vlan"][vlan["name"]]:
            if host["ipv6_address"] is None:
                continue
            data["hostname"] = host["hostname"]
            data["reverse"] = util.address.ipv6_hostpart(host["ipv6_address"], vlan["ipv6_subnet"].prefixlen)
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


def _forward_zone_file(cfg, zone_name, vlan, zone_file_name, zone_dir):
    zone_file = [_ZONE_TEMPLATE.format(zone_name, cfg["dns_domain"],)]
    cnames = [""]

    # static A / AAAA records for each host; CNAMEs for each alias (role name)
    for host in cfg["dns_entries_by_vlan"][vlan["name"]]:
        if host["ipv4_address"] != "dhcp":
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
    # insert as the first configured zone
    named["zones"].insert(0, _zone_config(cfg["domain"], cfg["domain"] + ".zone", True))

    # note not cfg["dns_domain"] for NS; top-level domain is required
    zone_file = [_ZONE_TEMPLATE.format(cfg["domain"], cfg["domain"])]

    # zone requires at least one entry
    iface = cfg["interfaces"][0]
    zone_file.append(_A.format_map({"hostname": cfg["hostname"], "ipv4_address": iface["ipv4_address"]}))
    if iface["ipv6_address"] is not None:
        zone_file.append(_AAAA.format_map({"hostname": cfg["hostname"], "ipv6_address": iface["ipv6_address"]}))

    util.file.write(cfg["domain"] + ".zone", "\n".join(zone_file), zone_dir)

    # no reverse zone needed since requests will be forwarded


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
