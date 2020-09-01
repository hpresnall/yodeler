"""Configuration & setup for the router VM."""
import util.file
import util.interfaces
import util.libvirt

import yodeler.interface

from roles.role import Role


class Router(Role):
    """Router defines the configuration needed to setup a system that can route from the configured
     vlans to the internet"""

    def __init__(self):
        super().__init__("router")

    def additional_configuration(self, cfg):
        # router will use Shorewall instead
        cfg["local_firewall"] = False

    def additional_packages(self):
        return {"shorewall", "shorewall6", "ipset", "radvd"
                "ulogd", "ulogd-json",
                "dhcpcd", "dhcrelay"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        uplink = cfg.get("uplink")

        if uplink is None:
            raise KeyError("router must define an uplink")

        # uplink can be an existing vswitch or a physical iface on the host via macvtap
        if "vswitch" in uplink:
            yodeler.interface.validate_network(uplink, cfg["vswitches"])
            uplink_xml = _vswitch_uplink(cfg, uplink["vswitch"], uplink.get("vlan"))
        elif "macvtap" in uplink:
            uplink_xml = util.libvirt.macvtap_interface(cfg, uplink["macvtap"])
        else:
            raise KeyError(("invald uplink in router; "
                            "it must define a vswitch+vlan or a macvtap host interface"))

        uplink["comment"] = "internet uplink"
        uplink["name"] = "eth0"
        # IPv6 dhcp managed by udhcpd not ifupdown
        uplink["ipv6_dhcp"] = False

        yodeler.interface.validate_iface(uplink)

        interfaces = [util.interfaces.loopback(), util.interfaces.from_config([uplink])]
        interface_elements = [uplink_xml]

        iface_counter = 1
        untagged = False

        for vswitch in cfg["vswitches"].values():
            vlan_interfaces = []
            iface_name = f"eth{iface_counter}"

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                if vlan["id"] is None:
                    untagged = True

                vlan_interfaces.append(util.interfaces.for_vlan(vlan, iface_name))

            if len(vlan_interfaces) > 0:
                comment = f"vlans on {vswitch['name']} vswitch"

                if untagged:  # parent interface already created; just output the comment
                    interfaces.append("# " + comment)
                else:  # create parent interface with the comment
                    interfaces.append(util.interfaces.port(iface_name, comment))

                interfaces.extend(vlan_interfaces)
                interface_elements.append(util.libvirt.router_interface(cfg['hostname'], vswitch))

                iface_counter += 1
            # else no routable interfaces => do not create anything

        # re-number defined interfaces
        for iface in cfg["interfaces"]:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        # rewrite interfaces with uplink and vswitches / vlans first
        interfaces.append(util.interfaces.from_config(cfg["interfaces"]))
        util.file.write("interfaces", "\n".join(interfaces), output_dir)

        util.libvirt.update_interfaces(cfg['hostname'], interface_elements, output_dir)
        return []


def _vswitch_uplink(cfg, vswitch, vlan):
    if vswitch not in cfg["vswitches"]:
        raise KeyError(f"invalid router uplink; vswitch {vswitch} does not exist")

    vswitch = cfg["vswitches"][vswitch]

    try:
        vlan = yodeler.interface.lookup_vlan(vlan, vswitch)
    except KeyError as err:
        msg = err.args[0]
        raise KeyError(f"invalid router uplink; {msg}")

    return util.libvirt.interface_from_config(cfg["hostname"], {"vswitch": vswitch, "vlan": vlan})
