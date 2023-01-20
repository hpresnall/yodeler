"""Configuration & setup for the main KVM & Openvswitch Alpine host."""
import os.path

import xml.etree.ElementTree as xml

from roles.role import Role

import config.interface as interface
import config.vlan as vlan


class VmHost(Role):
    """VmHost defines the configuration needed to setup a KVM host using OpenVswitch."""

    def __init__(self, cfg: dict):
        super().__init__("vmhost", cfg)

    def additional_packages(self):
        # packages for openvswitch, qemu, libvirt and alpine-make-vm-image
        return {"python3", "openvswitch", "qemu-system-x86_64", "qemu-img",
                "libvirt", "libvirt-daemon", "libvirt-qemu", "ovmf", "dbus", "polkit",
                "e2fsprogs", "rsync", "sfdisk", "git"}

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        # vm host needed if any other systems are vms
        for host_cfg in site_cfg["hosts"].values():
            if host_cfg["is_vm"]:
                return 1
        return 0

    def configure_interfaces(self):
        vswitch_interfaces = []

        for vswitch in self._cfg["vswitches"].values():
            vswitch_name = vswitch["name"]

            # iface for switch itself
            vswitch_interfaces.append(interface.for_port(vswitch_name, "vswitch"))

            vswitch_interfaces.extend(_create_uplink_ports(vswitch))

        # change original interface names to the open vswitch port name
        for iface in self._cfg["interfaces"]:
            # ifaces not net validated; manually look up vlan name
            iface_vswitch = self._cfg["vswitches"].get(iface.get("vswitch"))
            if not iface_vswitch:
                iface_vlan = "error" # interface validate will error before exposing this name in config files
            else:
                iface_vlan = vlan.lookup(iface.get(vlan), iface_vswitch)["name"]

            iface["name"] = f"{self._cfg['hostname']}-{iface_vlan}"
            iface["comment"] = "host interface"
            iface["parent"] = iface_vswitch["name"]

        self._cfg["interfaces"] = vswitch_interfaces + self._cfg["interfaces"]

    def additional_configuration(self):
        # do not support nested vms
        self._cfg["is_vm"] = False

    def validate(self):
        pass

    def write_config(self, setup, output_dir):
        _setup_open_vswitch(self._cfg, setup,)
        _setup_libvirt(self._cfg, setup, output_dir)

        # call yodel.sh for each VM
        setup.comment("run yodel.sh for each VM for this site")
        setup.append("cd $DIR/..") # site dir
        setup.blank()

        for _, host in self._cfg["hosts"].items():
            hostname = host["hostname"]

            if not host["is_vm"] or hostname == self._cfg["hostname"]:
                continue

            setup.append("echo \"Setting up VM '" + hostname + "'...\"")
            setup.append("cd ..")
            setup.append("cd " + hostname)
            setup.append("./yodel.sh")
            setup.blank()


def _create_uplink_ports(vswitch: dict) -> list[dict]:
    uplink = vswitch["uplink"]
    vswitch_name = vswitch["name"]

    if uplink is None:
        return []

    if isinstance(uplink, str):
        return [interface.for_port(uplink, f"uplink for vswitch {vswitch_name}", vswitch_name, uplink)]
    else:
        ifaces = []
        for n, iface in enumerate(uplink):
            ifaces.append(interface.for_port(
                iface, f"uplink {n+1} of {len(uplink)} for vswitch {vswitch_name}", vswitch_name, iface))
        return ifaces


def _setup_open_vswitch(cfg, setup):
    setup.substitute("templates/vmhost/openvswitch.sh", cfg)

    # create Open vswitches for each definiation
    # add uplink ports with correct tagging where specified
    for vswitch in cfg["vswitches"].values():
        vswitch_name = vswitch["name"]

        setup.comment(f"setup {vswitch_name} vswitch")
        setup.append(f"ovs-vsctl add-br {vswitch_name}")

        _create_vswitch_uplink(vswitch, setup)

    # each host interface needs a port on the vswitch
    for iface in cfg["interfaces"]:
        if iface["type"] != "std":
            continue

        port = f"{cfg['hostname']}-{iface['vlan']['name']}"

        setup.comment(f"setup switch port for host interface on vswitch {vswitch_name}")
        setup.append(
            f"ovs-vsctl add-port {vswitch_name} {port} -- set interface {port} type=internal")

        if iface["vlan"]["id"] is not None:
            setup.append(f"ovs-vsctl set port {port} tag={iface['vlan']['id']}")
            setup.append(f"ovs-vsctl set port {port} vlan_mode=access")

        setup.blank()


def _create_vswitch_uplink(vswitch, setup):
    # for each uplink, create a port on the vswitch
    uplink = vswitch["uplink"]

    if uplink is None:
        return []

    setup.blank()
    vswitch_name = vswitch["name"]

    if not isinstance(uplink, str):
        # multiple uplink interfaces; create a bond named 'uplink'
        bond_ifaces = " ".join(uplink)
        bond_name = f"{vswitch_name}-uplink"

        setup.comment("bonded uplink")
        setup.append(f"ovs-vsctl add-bond {vswitch_name} {bond_name} {bond_ifaces} lacp=active")

        uplink = bond_name  # use new uplink name for tagging, if needed
    else:
        setup.comment("uplink")
        setup.append(f"ovs-vsctl add-port {vswitch_name} {uplink}")

    # tag the uplink port
    vlans_by_id = vswitch["vlans_by_id"].keys()
    if len(vlans_by_id) == 1:
        # single vlan with id => access port
        if None not in vlans_by_id:
            tag = list(vlans_by_id)[0]
            setup.append(f"ovs-vsctl set port {uplink} tag={tag}")
            setup.append(f"ovs-vsctl set port {uplink} vlan_mode=access")
        # else no tagging needed
    elif len(vlans_by_id) > 1:  # multiple vlans => trunk port
        trunks = [str(vlan_id) for vlan_id in vlans_by_id if vlan_id != None]
        trunks = ",".join(trunks)
        setup.append(f"ovs-vsctl set port {uplink} trunks={trunks}")

        # native or PVID vlan => native_untagged
        # see http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt
        vlan_mode = "native_untagged" if None in vlans_by_id else "trunk"
        setup.append(f"ovs-vsctl set port {uplink} vlan_mode={vlan_mode}")

    setup.blank()


def _setup_libvirt(cfg, setup, output_dir):
    setup.substitute("templates/vmhost/libvirt.sh", cfg)

    # for each vswitch, create an XML network definition
    for vswitch in cfg["vswitches"].values():
        name = vswitch["name"]

        template = xml.parse("templates/vm/network.xml")
        net = template.getroot()

        net.find("name").text = name
        net.find("bridge").attrib["name"] = name

        # create a portgroup for the router that trunks all the routable vlans
        router_portgroup = xml.SubElement(net, "portgroup")
        router_portgroup.attrib["name"] = "router"
        router = xml.SubElement(router_portgroup, "vlan")
        router.attrib["trunk"] = "yes"
        routable = False

        # create a portgroup for each vlan
        for vlan in vswitch["vlans"]:
            portgroup = xml.SubElement(net, "portgroup")
            portgroup.attrib["name"] = vlan["name"]
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
        network_xml = name + ".xml"
        xml.indent(template, space="  ")
        template.write(os.path.join(output_dir, network_xml))

        setup.append(f"virsh net-define $DIR/{network_xml}")
        setup.append(f"virsh net-start {name}")
        setup.append(f"virsh net-autostart {name}")
        setup.blank()
