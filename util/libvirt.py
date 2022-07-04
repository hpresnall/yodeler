"""Utility functions for creating libvirt XML files."""
import xml.etree.ElementTree as xml
import os.path


def write_vm_xml(cfg, output_dir):
    """Create the libvirt XML for the given virtual machine."""
    template = xml.parse("templates/vm/server.xml")
    domain = template.getroot()

    domain.find("name").text = cfg["hostname"]
    domain.find("memory").text = str(cfg["memory_mb"])
    domain.find("vcpu").text = str(cfg["vcpus"])

    devices = domain.find("devices")

    devices.find("disk/source").attrib["file"] = f"{cfg['vm_images_path']}/{cfg['hostname']}.img"

    for iface in cfg["interfaces"]:
        devices.append(interface_from_config(cfg["hostname"], iface))

    xml.indent(template, space="  ")
    template.write(os.path.join(output_dir, cfg["hostname"] + ".xml"))


def interface_from_config(hostname, iface):
    """Create an <interface>  XML element for the given iface configuration.

    <interface type="network">
      <source network="<vswitch>" portgroup="<vlan>" />
      <target dev="<hostname>-<vlan>" />
      <model type="virtio" />
    </interface>
    """
    vlan_name = iface["vlan"]["name"]
    interface = xml.Element("interface")
    interface.attrib["type"] = "network"
    xml.SubElement(interface, "source",
                   {"network": iface["vswitch"]["name"], "portgroup": vlan_name})
    xml.SubElement(interface, "target", {"dev": f"{hostname}-{vlan_name}"})
    xml.SubElement(interface, "model", {"type": "virtio"})

    return interface


def macvtap_interface(cfg, iface_name):
    """Create an <interface> XML element that uses macvtap to connect the host's iface to the VM.
    The given iface_name is the name of the interface _on the host_.

    <interface type="direct">
      <source dev="<host_iface>" mode="private" />
      <model type="virtio" />
    </interface>
    """
    for vswitch in cfg["vswitches"].values():
        if "uplink" in vswitch and vswitch["uplink"] == iface_name:
            raise KeyError((f"invalid router uplink; "
                            f"cannot reuse uplink {iface_name} from vswitch {vswitch['name']}"))

    interface = xml.Element("interface")
    interface.attrib["type"] = "direct"
    xml.SubElement(interface, "source", {"dev": iface_name, "mode": "private"})
    xml.SubElement(interface, "model", {"type": "virtio"})

    return interface


def router_interface(hostname, vswitch):
    """Create an <interface> XML element that trunks all routable vlans on the given vwitch.

    <interface type="network">
      <source network="<vswitch>" portgroup="router" />
      <target dev="<hostname>-<vswitch>" />
      <model type="virtio" />
    </interface>
    """
    interface = xml.Element("interface")
    interface.attrib["type"] = "network"
    xml.SubElement(interface, "source",  {"network": vswitch["name"], "portgroup": "router"})
    xml.SubElement(interface, "target", {"dev": f"{hostname}-{vswitch['name']}"})
    xml.SubElement(interface, "model", {"type": "virtio"})

    return interface


def update_interfaces(hostname, new_interfaces, output_dir):
    """Update the interfaces in XML file for the given host.

    The new interfaces are added first, so the /etc/network/interfaces order must match."""
    file_name = os.path.join(output_dir, hostname + ".xml")
    template = xml.parse(file_name)
    devices = template.getroot().find("devices")

    # remove existing interfaces and add them back after the new ones
    original_interfaces = devices.findall("./interface")
    for original in original_interfaces:
        devices.remove(original)

    devices.extend(new_interfaces)
    devices.extend(original_interfaces)

    xml.indent(template, space="  ")
    template.write(file_name)
