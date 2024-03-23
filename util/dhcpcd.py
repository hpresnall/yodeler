"""Utility for /etc/dhcpcd.conf configuration."""
import util.file


def create_conf(cfg: dict, output_dir: str):
    """Create dhcpcd.conf and save it to the given directory.
    """
    conf = [util.file.read_template("common", "dhcpcd.conf")]

    interfaces = {}
    dhcp = False

    for iface in cfg["interfaces"]:
        # process uplink interfaces for dhcp and prefix delegation
        if iface["type"] in {"port", "vlan"}:
            continue

        buffer = []

        if iface["ipv4_address"] == "dhcp":
            dhcp = True
            buffer.append("  ipv4")

        if not iface["vlan"]["ipv6_disabled"] and not iface["ipv6_disabled"]:
            buffer.append("  ipv6")
            if iface["accept_ra"]:
                buffer.append("  ipv6rs")
            else:
                buffer.append("  noipv6rs")
        else:
            continue

        if iface["ipv6_dhcp"]:  # will not be set if ipv6_disabled is true
            dhcp = True
            buffer.append("")
            buffer.append("  # request a dhcp address")
            buffer.append("  ia_na 0")

        prefixes = iface.get("ipv6_delegated_prefixes")

        if prefixes:
            buffer.append("")
            prefixes.insert(0, f"  ia_pd 1/::{iface['ipv6_pd_prefixlen']}")
            buffer.append("  # request prefix delegation and distribute to all routable vlans")
            buffer.append(" ".join(prefixes))

        if iface["ipv6_ask_for_prefix"]:
            buffer.append("")
            buffer.append("  # request prefix delegation, but do not assign to any interfaces")
            buffer.append(f"  ia_pd 1/::{iface['ipv6_pd_prefixlen']}")

        if len(buffer) > 0:
            interfaces[iface["name"]] = buffer

    if interfaces:
        if dhcp:
            conf.append("# ifupdown will override this setting, contacting dhcpcd for interfaces explicitly requesting dhcp")
            conf.append("# this will also trigger ipv6 auto configuration, if needed")
            conf.append("denyinterfaces *")
        else:
            conf.append("# dhcpcd will be used for ipv6 auto configuration on only these interfaces")
            conf.append("# dhcpcd will wait for ifup")
            conf.append("allowinterfaces " + ", ".join(interfaces.keys()))
        conf.append("")

        for iface, buffer in interfaces.items():
            conf.append(f"interface {iface}")
            conf.append("\n".join(buffer))
            conf.append("")

        util.file.write("dhcpcd.conf", "\n".join(conf), output_dir)
