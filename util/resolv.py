"""Utility for /etc/resolv.confg configuration."""
import util.file as file

import config.interface as interface


def create_conf(cfg, output_dir):
    """Create resolv.conf and save it to the given directory.

    If DHCP or DHCP6 is used on any interfaces, no file is created.
    """
   # determine if any interface is using DHCP
    dhcp = False
    search_domains = []

    interfaces = cfg["interfaces"]

    for iface in interfaces:
        if iface["type"] != "std":
            continue

        dhcp |= iface["ipv4_address"] == "dhcp"
        dhcp |= iface["ipv6_dhcp"]

        # possibly search vlan domains
        domain = iface["vlan"]["domain"] if "vlan" in iface else None
        if domain:
            search_domains.append(domain)

    if dhcp:
        # do not write resolv.conf; assume DHCP will setup resolv.conf
        return

    # manually set DNS servers
    buffer = []

    # set domain for server
    if cfg["primary_domain"] != "":
        buffer.append(f"domain {cfg['primary_domain']}")

    dns_addresses = None
    if cfg["roles_to_hostnames"]["dns"]:
        dns_server = cfg["hosts"][cfg["roles_to_hostnames"]["dns"][0]]
        dns_addresses = interface.find_ips_to_interfaces(cfg, dns_server["interfaces"])

    if dns_addresses:
        # can search local domains if there is local DNS
        search_domains.append(cfg["domain"])

        buffer.append("search {}".format(" ".join(search_domains)))

        nameservers = [str(match["ipv4_address"]) for match in dns_addresses if match["ipv4_address"]]
        nameservers.extend([str(match["ipv6_address"]) for match in dns_addresses if match["ipv6_address"]])
    else:
        nameservers = cfg["external_dns"]

    for server in nameservers:
        buffer.append("nameserver " + server)
    buffer.append("")

    file.write("resolv.conf", "\n".join(buffer), output_dir)
