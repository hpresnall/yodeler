"""Utility for /etc/dhcpcd configuration."""
import util.file


def create_conf(cfg, output_dir):
    """Create dhcpcd.conf and save it to the given directory.
    """
    conf = [util.file.read("templates/common/dhcpcd.conf")]

    interfaces = {}

    for iface in cfg["interfaces"]:
        buffer = []
        if iface["ipv4_address"] == "dhcp":
            buffer.append("  ipv4")

        ipv6 = False

        if iface["accept_ra"]:
            buffer.append("  ipv6")
            ipv6 = True

        if iface["ipv6_dhcp"]:
            if not ipv6:
                buffer.append("  ipv6")
            buffer.append("  ia_na 0")

        prefixes = iface.get("ipv6_delegated_prefixes")

        if (prefixes is not None) and (len(prefixes) > 0):
            if not ipv6:
                buffer.append("  ipv6")
            prefixes.insert(0, f"  ia_pd 1/::{iface['ipv6_pd_prefixlen']}")
            buffer.append(" ".join(prefixes))

        if len(buffer) > 0:
            interfaces[iface["name"]] = buffer

    conf.append("allowinterfaces " + ", ".join(interfaces.keys()))
    conf.append("")

    for iface, buffer in interfaces.items():
        conf.append(f"interface {iface}")
        conf.append("\n".join(buffer))

    util.file.write("dhcpcd.conf", "\n".join(conf), output_dir)
