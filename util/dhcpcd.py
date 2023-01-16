"""Utility for /etc/dhcpcd.conf configuration."""
import util.file


def create_conf(cfg, output_dir):
    """Create dhcpcd.conf and save it to the given directory.
    """
    conf = [util.file.read("templates/common/dhcpcd.conf")]

    interfaces = {}

    for iface in cfg["interfaces"]:
        if ("type" in iface) and (iface["type"] in {"port", "vlan"}):
            continue
 
        buffer = []
        if iface["ipv4_address"] == "dhcp":
            buffer.append("  ipv4")

        ipv6 = False
        ra = False

        if iface["accept_ra"]:
            ra = True
            # on by default with ipv6; no addition config needed

        if iface["ipv6_dhcp"]:
            buffer.append("  ipv6")
            if not ra:
                buffer.append("  noipv6rs")

            buffer.append(" ")
            buffer.append("  # request a dhcp address")
            buffer.append("  ia_na 0")
            ipv6 = True

        prefixes = iface.get("ipv6_delegated_prefixes")

        if (prefixes is not None) and (len(prefixes) > 0):
            if not ipv6:
                buffer.append("  ipv6")
                if not ra:
                    buffer.append("  noipv6rs")
                ipv6 = True

            prefixes.insert(0, f"  ia_pd 1/::{iface['ipv6_pd_prefixlen']}")

            buffer.append(" ")
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
