"""Utility functions for creating libvirt XML files."""
import xml.etree.ElementTree as xml
import os.path


def write_vm_xml(cfg, output_dir):
    """Create the libvirt XML for the given virtual machine."""
    template = xml.parse("templates/vm/server.xml")
    domain = template.getroot()

    _find_and_set_text(domain, "name", cfg["hostname"])
    _find_and_set_text(domain, "memory", str(cfg["memory_mb"]))
    _find_and_set_text(domain, "vcpu", str(cfg["vcpus"]))

    devices = domain.find("devices")

    if devices is None:
        devices = xml.SubElement(domain, "devices")

    source = devices.find("disk/source")

    if source is None:
        disk = devices.find("disk")
        if disk is None:
            disk = xml.SubElement(devices, "disk")
        source = xml.SubElement(disk, "source")

    source.attrib["file"] = f"{cfg['vm_images_path']}/{cfg['hostname']}.img"

    for iface in cfg["interfaces"]:
        if iface["type"] != "std":
            continue
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
    xml.SubElement(interface, "source", {"network": iface["vswitch"]["name"], "portgroup": vlan_name})
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
            raise KeyError((f"invalid router uplink; cannot reuse uplink {iface_name} from vswitch {vswitch['name']}"))

    interface = xml.Element("interface")
    interface.attrib["type"] = "direct"
    xml.SubElement(interface, "source", {"dev": iface_name, "mode": "private"})
    xml.SubElement(interface, "model", {"type": "virtio"})

    return interface


def router_interface(hostname, vswitch):
    """Create an <interface> XML element that trunks all routable vlans on the given vswitch.

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

    if devices is None:
        devices = xml.SubElement(template.getroot(), "devices")

    # remove existing interfaces and add them back after the new ones
    original_interfaces = devices.findall("./interface")
    for original in original_interfaces:
        devices.remove(original)

    devices.extend(new_interfaces)
    devices.extend(original_interfaces)

    xml.indent(template, space="  ")
    template.write(file_name)


def create_network(vswitch, output_dir):
    """Create a libvirt XML file for the given vswitch and write it to <vswitch[name]>.xml.

    Creates a portgroup for each vlan. For every routable vlan, adds that vlan to a 'router' portgroup that creates a
    trunk port on the vswitch that can be used by a router as an uplink.
    """
    vswitch_name = vswitch["name"]

    net = xml.Element("network")
    name = xml.SubElement(net, "name")
    name.text = vswitch_name
    xml.SubElement(net, "virtualport", {"type": "openvswitch"})
    xml.SubElement(net, "forward", {"mode": "bridge"})
    xml.SubElement(net, "bridge", {"name": vswitch_name})

    # create a portgroup for the router that trunks all the routable vlans
    router_portgroup = xml.SubElement(net, "portgroup", {"name": "router"})
    router = xml.SubElement(router_portgroup, "vlan")
    router.attrib["trunk"] = "yes"
    routable = False

    # create a portgroup for each vlan
    for vlan in vswitch["vlans"]:
        portgroup = xml.SubElement(net, "portgroup", {"name": vlan["name"]})
        vlan_id = vlan["id"]

        if vlan["default"]:
            portgroup.attrib["default"] = "yes"

        if vlan_id is not None:
            vlan_xml = xml.SubElement(portgroup, "vlan")
            tag = xml.SubElement(vlan_xml, "tag")
            tag.attrib["id"] = str(vlan_id)

        # add to router portgroup
        if vlan["routable"]:
            routable = True
            tag = xml.SubElement(router, "tag")

            if vlan_id is None:
                tag.attrib["id"] = "0"  # id required; use 0 for untagged
                tag.attrib["nativeMode"] = "untagged"
            else:
                tag.attrib["id"] = str(vlan_id)

    # no routable vlans on the vswitch, remove the router portgroup
    if not routable:
        net.remove(router_portgroup)

    # save the file and add the virsh commands to the script
    network_xml = vswitch_name + ".xml"
    xml.indent(net, space="  ")
    xml.ElementTree(net).write(os.path.join(output_dir, network_xml))


def _find_and_set_text(root: xml.Element, element_name: str, text: str):
    e = root.find(element_name)

    if e is None:
        e = xml.SubElement(root, element_name)

    e.text = text
