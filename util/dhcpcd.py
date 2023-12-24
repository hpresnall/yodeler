"""Utility for /etc/dhcpcd.conf configuration."""
import util.file


def create_conf(cfg: dict, output_dir: str):
    """Create dhcpcd.conf and save it to the given directory.
    """
    conf = [util.file.read("templates/common/dhcpcd.conf")]

    interfaces = {}

    for iface in cfg["interfaces"]:
        # process uplink interfaces for dhcp and prefix delegation
        if iface["type"] in {"port", "vlan"}:
            continue

        buffer = []

        if iface["ipv4_address"] == "dhcp":
            buffer.append("  ipv4")

        ipv6 = False

        if not iface["vlan"]["ipv6_disabled"] and not iface["ipv6_disabled"]:
            if iface["accept_ra"]:
                ipv6 = True
                buffer.append("  ipv6")
                buffer.append("  ipv6rs")

        if iface["ipv6_dhcp"]:  # will not be set if ipv6_disabled is true
            if not ipv6:
                ipv6 = True
                buffer.append("  ipv6")
            buffer.append(" ")
            buffer.append("  # request a dhcp address")
            buffer.append("  ia_na 0")

        prefixes = iface.get("ipv6_delegated_prefixes")

        if prefixes or iface.get("ipv6_ask_for_prefix"):
            if not ipv6:
                buffer.append("  ipv6")
                if not iface["accept_ra"]:
                    buffer.append("  noipv6rs")

            buffer.append(" ")

            if iface["ipv6_ask_for_prefix"]:
                buffer.append("  # request prefix delegation, but do not assign to any interfaces")
                buffer.append(f"  ia_pd 1/::{iface['ipv6_pd_prefixlen']}")
            else:
                prefixes.insert(0, f"  ia_pd 1/::{iface['ipv6_pd_prefixlen']}")
                buffer.append("  # request prefix delegation and distribute to all routable vlans")
                buffer.append(" ".join(prefixes))

        if len(buffer) > 0:
            interfaces[iface["name"]] = buffer

    if interfaces:
        conf.append("allowinterfaces " + ", ".join(interfaces.keys()))
        conf.append("")

        for iface, buffer in interfaces.items():
            conf.append(f"interface {iface}")
            conf.append("\n".join(buffer))
        conf.append("")

        util.file.write("dhcpcd.conf", "\n".join(conf), output_dir)
