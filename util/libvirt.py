"""Utility functions for creating libvirt XML files."""
import xml.etree.ElementTree as xml
import os.path


def write_vm_xml(cfg: dict, output_dir: str) -> None:
    """Create the libvirt XML for the given virtual machine."""
    template = xml.parse("templates/vm/vm.xml")
    domain = template.getroot()

    _find_and_set_text(domain, "name", cfg["hostname"])
    _find_and_set_text(domain, "memory", str(cfg["memory_mb"]))
    _find_and_set_text(domain, "vcpu", str(cfg["vcpus"]))

    devices = domain.find("devices")

    if devices is None:
        devices = xml.SubElement(domain, "devices")

    disk_devs = set()
    disks = devices.findall("disk")

    for disk in disks:
        target = disk.find("target")
        if (target is not None) and ("dev" in target.attrib):
            disk_devs.add(target.attrib["dev"])

    for i, disk_path in enumerate(cfg["vm_disk_paths"]):
        disk_dev = "vd" + chr(ord('a')+i)  # vda, vdb etc

        # ensure unique dev name for each VM
        while disk_dev in disk_devs:
            disk_dev = "vd" + chr(ord('a')+i)
        disk_devs.add(disk_dev)

        devices.append(create_disk(disk_dev, disk_path))

    for iface in cfg["interfaces"]:
        if iface["type"] != "std":
            continue
        devices.append(interface_from_config(cfg["hostname"], iface))

    if cfg["host_share"]:
        devices.append(_create_host_share(cfg["vm_images_path"] + "/shared", "shared"))
    if cfg["host_backup"]:
        devices.append(_create_host_share(cfg["vm_images_path"] + "/backup/" + cfg["hostname"], "backup"))

    xml.indent(template, space="  ")

    template.write(os.path.join(output_dir, cfg["hostname"] + ".xml"))


def create_disk(disk_dev: str, disk_path: str) -> xml.Element:
    """Create a <disk> XML element for the given disk.

        <disk type="file" device="disk">
        <driver name="qemu" type="raw" />
        <source file="<path_to_img>" />
        <target dev="<disk_name>" bus="virtio" />
        </disk>
    """
    disk = xml.Element("disk", {"type": "file", "device": "disk"})
    xml.SubElement(disk, "driver", {"name": "qemu", "type": "raw"})
    xml.SubElement(disk, "source", {"file": disk_path})
    xml.SubElement(disk, "target", {"dev": disk_dev, "bus": "virtio"})

    return disk


def interface_from_config(hostname: str, iface: dict) -> xml.Element:
    """Create an <interface> XML element for the given iface configuration.

    <interface type="network">
      <source network="<vswitch>" portgroup="<vlan>" />
      <target dev="<hostname>-<vlan>" />
      <model type="virtio" />
    </interface>
    """
    vlan_name = iface["vlan"]["name"]
    interface = xml.Element("interface", {"type": "network"})
    device = f"{hostname}-{vlan_name}"[:15]  # Linux device names much be < 16 characters
    xml.SubElement(interface, "source", {"network": iface["vswitch"]["name"], "portgroup": vlan_name})
    xml.SubElement(interface, "target", {"dev": device})
    xml.SubElement(interface, "model", {"type": "virtio"})

    return interface


def macvtap_interface(cfg: dict, iface_name: str) -> xml.Element:
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

    interface = xml.Element("interface", {"type": "direct"})
    xml.SubElement(interface, "source", {"dev": iface_name, "mode": "private"})
    xml.SubElement(interface, "model", {"type": "virtio"})

    return interface


def router_interface(hostname: str, vswitch: dict) -> xml.Element:
    """Create an <interface> XML element that trunks all routable vlans on the given vswitch.

    <interface type="network">
      <source network="<vswitch>" portgroup="router" />
      <target dev="<hostname>-<vswitch>" />
      <model type="virtio" />
    </interface>
    """
    interface = xml.Element("interface", {"type": "network"})
    xml.SubElement(interface, "source",  {"network": vswitch["name"], "portgroup": "router"})
    xml.SubElement(interface, "target", {"dev": f"{hostname}-{vswitch['name']}"})
    xml.SubElement(interface, "model", {"type": "virtio"})

    return interface


def update_interfaces(hostname: str, new_interfaces: list[xml.Element], output_dir: str) -> None:
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


def create_network(vswitch: dict, output_dir: str) -> None:
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
    router = xml.SubElement(router_portgroup, "vlan", {"trunk": "yes"})
    routable = False

    # create a portgroup for each vlan
    for vlan in vswitch["vlans"]:
        portgroup = xml.SubElement(net, "portgroup", {"name": vlan["name"]})
        vlan_id = vlan["id"]

        if vlan["default"]:
            portgroup.attrib["default"] = "yes"

        if vlan_id is not None:
            vlan_xml = xml.SubElement(portgroup, "vlan")
            tag = xml.SubElement(vlan_xml, "tag", {"id": str(vlan_id)})

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


def _create_host_share(vmhost_path: str, share_name: str) -> xml.Element:
    """Create an <filesystem> XML element for a directory shared with the KVM host.

    <filesystem type='mount' accessmode='passthrough'>                           
      <driver type='virtiofs'/>                         
      <binary path="/usr/lib/qemu/virtiofsd"/>
      <source dir='<path>'/>                  
      <target dir='<name>'/>                                                  
    </filesystem>
    """
    filesystem = xml.Element("filesystem", {"type": "mount", "accessmode": "passthrough"})
    xml.SubElement(filesystem, "driver", {"type": "virtiofs"})
    xml.SubElement(filesystem, "binary",  {"path": "/usr/lib/qemu/virtiofsd"})
    xml.SubElement(filesystem, "source", {"dir": vmhost_path})
    xml.SubElement(filesystem, "target", {"dir": share_name})

    return filesystem


def _find_and_set_text(root: xml.Element, element_name: str, text: str) -> None:
    e = root.find(element_name)

    if e is None:
        e = xml.SubElement(root, element_name)

    e.text = text
