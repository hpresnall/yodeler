"""Utility for /etc/resolv.confg configuration."""
import util.file


def create_conf(cfg, output_dir):
    """Create resolv.conf and save it to the given directory.

    If DHCP or DHCP6 is used on any interfaces, no file is created.
    """
   # determine if any interface is using DHCP
    dhcp = False
    search_domains = []

    interfaces = cfg["interfaces"]

    for iface in interfaces:
        dhcp |= iface["ipv4_address"] == "dhcp"
        dhcp |= iface["ipv6_dhcp"]

        # possibly search vlan domains
        domain = iface["vlan"].get("domain") if "vlan" in iface else None
        if domain:
            search_domains.append(domain)

    if dhcp:
        # do not write resolv.conf; assume DHCP will setup resolv.conf
        return

    # manually set DNS servers
    buffer = []

    local_dns = cfg["local_dns"]
    if local_dns:
        # set domain for server
        if cfg["primary_domain"] != "":
            buffer.append(f"domain {cfg['primary_domain']}")

        # can search local domains if there is local DNS
        search_domains.append(cfg["domain"])

        buffer.append("search {}".format(" ".join(search_domains)))

        nameservers = local_dns
    else:
        nameservers = cfg["external_dns"]

    for server in nameservers:
        buffer.append("nameserver " + server)
    buffer.append("")

    util.file.write("resolv.conf", "\n".join(buffer), output_dir)
