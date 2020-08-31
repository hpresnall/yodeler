"""Configuration & setup for the router VM."""
import xml.etree.ElementTree as xml
import os.path

import util.file
import util.interfaces

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
            uplink_xml = _vswitch_uplink(cfg, uplink["vswitch"], uplink.get("vlan"))
            yodeler.interface.validate_network(uplink, cfg["vswitches"])
        elif "macvtap" in uplink:
            uplink_xml = _macvtap_uplink(cfg, uplink["macvtap"])
        else:
            raise KeyError(("invald uplink in router; "
                            "it must define a vswitch+vlan or a macvtap host interface"))

        uplink["comment"] = "internet uplink"
        uplink["name"] = "eth0"
        # IPv6 dhcp managed by udhcpd not ifupdown
        uplink["ipv6_dhcp"] = False

        yodeler.interface.validate_iface(uplink)

        interfaces = [util.interfaces.loopback(), util.interfaces.as_etc_network([uplink])]
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

                vlan_interfaces.append(util.interfaces.create_for_vlan(vlan, iface_name))

            if len(vlan_interfaces) > 0:
                comment = f"vlans on {vswitch['name']} vswitch"

                if untagged:  # parent interface already created; just output the comment
                    interfaces.append("# " + comment)
                else:  # create parent interface with the comment
                    interfaces.append(util.interfaces.create_port(iface_name, comment))

                interfaces.extend(vlan_interfaces)

                # add an interface to the VM
                interface = xml.Element("interface")
                interface.attrib["type"] = "network"
                xml.SubElement(interface, "source",
                               {"network": vswitch["name"], "portgroup": "router"})
                xml.SubElement(interface, "target", {"dev": f"{cfg['hostname']}-{vswitch['name']}"})
                xml.SubElement(interface, "model", {"type": "virtio"})

                interface_elements.append(interface)

                iface_counter += 1
            # else no routable interfaces => do not create anything

        # re-number defined interfaces
        for iface in cfg["interfaces"]:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        # rewrite interfaces with uplink and vswitches / vlans first
        interfaces.append(util.interfaces.as_etc_network(cfg["interfaces"]))
        util.file.write("interfaces", "\n".join(interfaces), output_dir)

        _recreate_network_xml(cfg, interface_elements, output_dir)
        return []


def _macvtap_uplink(cfg, iface):
    for vswitch in cfg["vswitches"].values():
        if "uplink" in vswitch and vswitch["uplink"] == iface:
            raise KeyError((f"invalid router uplink; "
                            f"cannot reuse uplink {iface} from vswitch {vswitch['name']}"))

    interface = xml.Element("interface")
    interface.attrib["type"] = "direct"
    xml.SubElement(interface, "source", {"dev": iface, "mode": "private"})

    return interface


def _vswitch_uplink(cfg, vswitch, vlan):
    if vswitch not in cfg["vswitches"]:
        raise KeyError(f"invalid router uplink; vswitch {vswitch} does not exist")

    vswitch = cfg["vswitches"][vswitch]

    try:
        vlan = yodeler.interface.lookup_vlan(vlan, vswitch)
    except KeyError as err:
        msg = err.args[0]
        raise KeyError(f"invalid router uplink; {msg}")

    return yodeler.interface.libvirt_xml(cfg["hostname"], {"vswitch": vswitch, "vlan": vlan})


def _recreate_network_xml(cfg, interface_elements, output_dir):
    file_name = os.path.join(output_dir, cfg["hostname"] + ".xml")
    template = xml.parse(file_name)
    devices = template.getroot().find("devices")

    # remove existing interfaces and add them back after the new ones
    original_interfaces = devices.findall("./interface")
    for original in original_interfaces:
        devices.remove(original)

        devices.extend(interface_elements)
        devices.extend(original_interfaces)

        template.write(file_name)
