"""Configuration & setup for the main KVM & Openvswitch Alpine host."""
import os.path
import xml.etree.ElementTree as xml
import shutil

import util.shell
import util.file
import util.interfaces
import util.awall
import util.resolv

from roles.role import Role

import yodeler.interface


class VmHost(Role):
    """VmHost defines the configuration needed to setup a KVM host using OpenVswitch."""

    def __init__(self):
        super().__init__("vmhost")

    def additional_packages(self):
        return {"python3", "openvswitch", "qemu-system-x86_64", "qemu-img",
                "libvirt", "libvirt-daemon", "libvirt-qemu", "dbus", "polkit", "git"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        scripts = []

        scripts.append(_setup_open_vswitch(cfg, output_dir))
        scripts.append(_setup_libvirt(cfg, output_dir))

#        _configure_initial_network(cfg, output_dir)
        return scripts


def _setup_open_vswitch(cfg, output_dir):
    shell = util.shell.ShellScript("openvswitch.sh")
    shell.substitute("templates/vmhost/openvswitch.sh", cfg)

    # create new entries in /etc/network/interfaces for each switch
    vswitch_interfaces = []
    uplink_interfaces = []

    # create Open vswitches for each configuration
    # create interfaces for each switch
    # add uplink ports with correct tagging where specified
    for vswitch in cfg["vswitches"].values():
        vswitch_name = vswitch["name"]
        shell.append(f"# setup {vswitch_name} vswitch")
        shell.append(f"ovs-vsctl add-br {vswitch_name}")

        # iface for switch itself
        iface = util.interfaces.port(vswitch_name, "vswitch")
        vswitch_interfaces.append(iface)

        uplink_interfaces += _configure_uplinks(shell, vswitch)

    cfg["vmhost_interfaces"] = vswitch_interfaces + uplink_interfaces

    _reconfigure_interfaces(shell, cfg, output_dir)

    return shell.name


def _configure_uplinks(shell, vswitch):
    # for each uplink, create a port on the vswitch and an iface definition
    uplink = vswitch["uplink"]
    if uplink is None:
        shell.append("")
        return []

    vswitch_name = vswitch["name"]
    uplink_interfaces = []

    if not isinstance(uplink, str):
        # multiple uplink interfaces; create a bond named 'uplink'
        uplink = "uplink"
        bond_ifaces = " ".join(uplink)
        shell.append(f"ovs-vsctl add-bond {vswitch_name} {uplink} {bond_ifaces} lacp=active")

        for iface in uplink:
            iface = util.interfaces.port(uplink, "uplink for vswitch " + vswitch_name)
            uplink_interfaces.append(iface)
    else:
        shell.append(f"ovs-vsctl add-port {vswitch_name} {uplink}")
        iface = util.interfaces.port(uplink, "uplink for vswitch " + vswitch_name)
        uplink_interfaces.append(iface)

    # tag the uplink port
    vlans_by_id = vswitch["vlans_by_id"].keys()
    if len(vlans_by_id) == 1:
        # single vlan with id => access port
        if None not in vlans_by_id:
            tag = list(vlans_by_id)[0]
            shell.append(f"ovs-vsctl set port {uplink} tag={tag}")
            shell.append(f"ovs-vsctl set port {uplink} vlan_mode=access")
        # else no tagging needed
    elif len(vlans_by_id) > 1:  # multiple vlans => trunk port
        trunks = [str(vlan_id) for vlan_id in vlans_by_id
                  if vlan_id != "None"]
        trunks = ",".join(trunks)
        shell.append(f"ovs-vsctl set port {uplink} trunks={trunks}")

        # native or PVID vlan => native_untagged
        # see http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt
        vlan_mode = "native_untagged" if None in vlans_by_id else "trunk"
        shell.append(f"ovs-vsctl set port {uplink} vlan_mode={vlan_mode}")

    shell.append("")

    return uplink_interfaces


def _reconfigure_interfaces(shell, cfg, output_dir):
    if cfg["local_firewall"]:
        # replace existing interfaces with new vswitch port names
        awall_base = util.file.read("awall/base.json", output_dir)

    # each host interface needs a port on the vswitch too
    # change original interface name to the port name
    for iface in cfg["interfaces"]:
        vswitch_name = iface["vswitch"]["name"]
        port = f"{cfg['hostname']}-{vswitch_name}"

        if cfg["local_firewall"]:
            awall_base = awall_base.replace(iface["name"], port)

        iface["name"] = port
        iface["comment"] = "host interface"

        shell.append(f"# setup switch port for host interface on vswitch {vswitch_name}")
        shell.append(
            f"ovs-vsctl add-port {vswitch_name} {port} -- set interface {port} type=internal")

        if iface["vlan"]["id"] is not None:
            shell.append(f"ovs-vsctl set port {port} tag={iface['vlan']['id']}")
            shell.append(f"ovs-vsctl set port {port} vlan_mode=access")

        shell.append("")

    shell.write_file(output_dir)

    # overwrite the original interfaces file from common setup
    # vswitch & uplink ifaces first so they are up before the vm host's ports
    interfaces = [util.interfaces.loopback()]
    interfaces.extend(cfg["vmhost_interfaces"])
    interfaces.append(util.interfaces.from_config(cfg["interfaces"]))

    util.file.write("interfaces", "\n".join(interfaces), output_dir)

    # overwrite the original awall base config
    if cfg["local_firewall"]:
        util.file.write("awall/base.json", awall_base, output_dir)


def _setup_libvirt(cfg, output_dir):
    shell = util.shell.ShellScript("libvirt.sh")
    #shell.setup_logging(cfg["hostname"])
    shell.substitute("templates/vmhost/libvirt.sh", cfg)

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
        template.write(os.path.join(output_dir, network_xml))

        shell.append(f"virsh net-define $DIR/{network_xml}")
        shell.append(f"virsh net-start {name}")
        shell.append(f"virsh net-autostart {name}")
        shell.append("")

    shell.write_file(output_dir)

    return shell.name