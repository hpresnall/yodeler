"""Utility for /etc/resolv.confg configuration."""
import util.file as file

import config.interface as interface


def create_conf(cfg: dict, output_dir: str):
    """Create resolv.conf and save it to the given directory.

    If DHCP or DHCP6 is used on any interfaces, no file is created.
    """
    resolv_conf = "resolv.conf"
    head = False  # for uplinks using dhcp, write to resolv.conf.head

    search_domains = []

    for iface in cfg["interfaces"]:
        if iface["ipv4_address"] == "dhcp" or iface["ipv6_dhcp"]:
            if iface["type"] == "std":
                return  # dhcp will handle
            if iface["type"] == "uplink":
                head = True  # let uplink dhcp create resolv.conf but add site content

        if iface["type"] in {"std", "vlan"}:
            # possibly search vlan domains
            if iface["vlan"]["domain"]:
                search_domains.append(iface["vlan"]["domain"])

    if head:
        # write to head so this config is combined with what dhcp returns
        resolv_conf = "resolv.conf.head"

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

    file.write(resolv_conf, "\n".join(buffer), output_dir)
