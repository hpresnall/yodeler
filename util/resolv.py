"""Utility for /etc/resolv.conf configuration."""
import util.file as file

import config.interface as interface


def create_conf(cfg: dict) -> str:
    """Create resolv.conf file as a string."""
    search_domains = []

    for iface in cfg["interfaces"]:
        # possibly search vlan domains
        if iface["type"] in {"std", "vlan"} and iface["vlan"]["domain"]:
            search_domains.append(iface["vlan"]["domain"])

    buffer = []

    # set domain for server
    if cfg["primary_domain"] != "":
        buffer.append(f"domain {cfg['primary_domain']}")

    dns_addresses = []
    if "dns" in cfg["roles_to_hostnames"] and cfg["roles_to_hostnames"]["dns"]:
        for hostname in cfg["roles_to_hostnames"]["dns"]:
            dns_server = cfg["hosts"][hostname]
            dns_addresses.extend(interface.find_ips_to_interfaces(cfg, dns_server["interfaces"]))

    if dns_addresses:
        # search local domains if there is local DNS
        search_domains.append(cfg["domain"])

        buffer.append("search {}".format(" ".join(search_domains)))

        nameservers = [str(match["ipv4_address"]) for match in dns_addresses if match["ipv4_address"]]
        nameservers.extend([str(match["ipv6_address"]) for match in dns_addresses if match["ipv6_address"]])
    else:
        nameservers = cfg["external_dns"]

    for server in nameservers:
        buffer.append("nameserver " + server)
    buffer.append("")

    return "\n".join(buffer)
