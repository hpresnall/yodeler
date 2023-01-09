"""Configuration & setup for the main KVM & Openvswitch Alpine host."""
import os.path

import xml.etree.ElementTree as xml

import util.shell
import util.file
import util.interfaces
import util.awall
import util.resolv
import util.dhcpcd

from roles.role import Role

import config.interface


class VmHost(Role):
    """VmHost defines the configuration needed to setup a KVM host using OpenVswitch."""

    def __init__(self):
        super().__init__("vmhost")

    def additional_packages(sel, cfg):
        # packages for openvswitch, qemu, libvirt and alpine-make-vm-image
        return {"python3", "openvswitch", "qemu-system-x86_64", "qemu-img",
                "libvirt", "libvirt-daemon", "libvirt-qemu", "ovmf", "dbus", "polkit", 
                "e2fsprogs", "rsync", "sfdisk", "git"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        scripts = []

        scripts.append(_setup_open_vswitch(cfg, output_dir))
        scripts.append(_setup_libvirt(cfg, output_dir))
        scripts.append(_setup_vms(cfg, output_dir))

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
        iface = util.interfaces.port(vswitch_name, None, "vswitch")
        vswitch_interfaces.append(iface)

        uplink_interfaces.extend(_configure_uplinks(cfg, shell, vswitch))

    _reconfigure_interfaces(shell, cfg, output_dir)

    # overwrite the original interfaces file from common setup
    # vswitch & uplink ifaces first
    interfaces = [util.interfaces.loopback()]
    interfaces.extend(vswitch_interfaces)
    interfaces.extend(uplink_interfaces)
    interfaces.append(util.interfaces.from_config(cfg["interfaces"]))

    util.file.write("interfaces", "\n".join(interfaces), output_dir)

    # rewrite dhcpcd.conf with new interface names
    util.dhcpcd.create_conf(cfg, output_dir)

    return shell.name


def _configure_uplinks(cfg, shell, vswitch):
    # for each uplink, create a port on the vswitch and an iface definition
    uplink = vswitch["uplink"]
    if uplink is None:
        shell.append("")
        return []

    vswitch_name = vswitch["name"]
    uplink_interfaces = []

    if not isinstance(uplink, str):
        # multiple uplink interfaces; create a bond named 'uplink'
        bond_ifaces = " ".join(uplink)
        bond_name = f"{vswitch_name}-uplink"
        shell.append("# bonded uplink")
        shell.append(f"ovs-vsctl add-bond {vswitch_name} {bond_name} {bond_ifaces} lacp=active")

        for n, iface in enumerate(uplink):
            bond = util.interfaces.port(iface, vswitch_name, f"uplink {n+1} of {len(uplink)} for vswitch {vswitch_name}",
                                        config.interface.find_by_name(cfg, iface))
            uplink_interfaces.append(bond)
        uplink = bond_name  # use new uplink name for tagging, if needed
    else:
        shell.append("# uplink")
        shell.append(f"ovs-vsctl add-port {vswitch_name} {uplink}")
        iface = util.interfaces.port(uplink, vswitch_name, "uplink for vswitch " + vswitch_name,
                                     config.interface.find_by_name(cfg, uplink))
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
        trunks = [str(vlan_id) for vlan_id in vlans_by_id if vlan_id != "None"]
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

    # change original interface name to the port name
    for iface in cfg["interfaces"]:
        vswitch_name = iface["vswitch"]["name"]
        port = f"{cfg['hostname']}-{iface['vlan']['name']}"

        if cfg["local_firewall"]:
            awall_base = awall_base.replace(iface["name"], port)

        iface["name"] = port
        iface["comment"] = "host interface"
        iface["parent"] = vswitch_name

        # each host interface needs a port on the vswitch too
        shell.append(f"# setup switch port for host interface on vswitch {vswitch_name}")
        shell.append(
            f"ovs-vsctl add-port {vswitch_name} {port} -- set interface {port} type=internal")

        if iface["vlan"]["id"] is not None:
            shell.append(f"ovs-vsctl set port {port} tag={iface['vlan']['id']}")
            shell.append(f"ovs-vsctl set port {port} vlan_mode=access")

        shell.append("")

    shell.write_file(output_dir)

    # overwrite the original awall base config
    if cfg["local_firewall"]:
        util.file.write("awall/base.json", awall_base, output_dir)


def _setup_libvirt(cfg, output_dir):
    shell = util.shell.ShellScript("libvirt.sh")
    # shell.setup_logging(cfg["hostname"])
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
        xml.indent(template, space="  ")
        template.write(os.path.join(output_dir, network_xml))

        shell.append(f"virsh net-define $DIR/{network_xml}")
        shell.append(f"virsh net-start {name}")
        shell.append(f"virsh net-autostart {name}")
        shell.append("")

    shell.write_file(output_dir)

    return shell.name

def _setup_vms(cfg, output_dir):
    shell = util.shell.ShellScript("create_vms.sh")
    shell.append("# run create_vm.sh for each VM for this site")
    shell.append("cd $DIR")
    shell.append("")

    for _, host in cfg["hosts"].items():
        hostname = host["hostname"]

        if not host["is_vm"] or hostname == cfg["hostname"]:
            continue

        shell.append("echo \"Setting up VM " + hostname + "...\"")
        shell.append("cd ..")
        shell.append("cd " + hostname)
        shell.append("./create_vm.sh")
        shell.append("")

    shell.write_file(output_dir)

    return shell.name