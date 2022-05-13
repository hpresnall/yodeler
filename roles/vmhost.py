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

        # libvirt cannot be started by locald, so create a 2nd locald script
        # for doing the rest of the config
        _configure_libvirt(cfg, output_dir)

        _configure_initial_network(cfg, output_dir)

        # note bootstrap and locald_setup are _separate_ scripts run outside of setup.sh
        return scripts


def _setup_open_vswitch(cfg, output_dir):
    shell = util.shell.ShellScript("openvswitch.sh")
    shell.append(_SETUP_OVS)

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
    shell.substitute("templates/vmhost/libvirt.sh", cfg)
    shell.write_file(output_dir)

    return shell.name


# actions to run _after_ libvirtd is started
def _configure_libvirt(cfg, output_dir):
    shell = util.shell.ShellScript("libvirt.start")
    shell.setup_logging(cfg["hostname"])
    shell.substitute("templates/vmhost/locald_libvirt.sh", cfg)

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

    shell.append("# remove from local.d so setup is only run once")
    shell.append("rm $0")

    shell.write_file(output_dir)


def _configure_initial_network(cfg, output_dir):
    if "initial_interfaces" not in cfg:
        return

    # move final config
    shutil.move(os.path.join(output_dir, "awall"),
                os.path.join(output_dir, "awall.final"))
    shutil.move(os.path.join(output_dir, "interfaces"),
                os.path.join(output_dir, "interfaces.final"))
    shutil.move(os.path.join(output_dir, "resolv.conf"),
                os.path.join(output_dir, "resolv.conf.final"))

    # create interfaces for initial setup
    initial_interfaces = cfg["initial_interfaces"]
    names = set()

    for i, iface in enumerate(initial_interfaces):
        # usual configuration numbers ifaces by array order
        # initial config may not use all ifaces, so name must be specified
        # to ignore ordering
        if "name" not in iface:
            raise KeyError(f"name not defined for initial interface {i}: {iface}")

        if iface["name"] in names:
            raise KeyError(f"duplicate name defined for initial interface {i}: {iface}")
        names.add(iface["name"])

        try:
            if "vswitch" in iface:
                yodeler.interface.validate_network(iface, cfg["vswitches"])
            yodeler.interface.validate_iface(iface)
        except KeyError as err:
            msg = err.args[0]
            raise KeyError(f"{msg} for initial_interface {i}: {iface}")

        iface["firewall_zone"] = "initial_" + iface["name"]

    # script to switch network to final configuration
    shell = util.shell.ShellScript("finalize_network.sh")
    shell.append_self_dir()
    shell.append_rootinstall()
    shell.setup_logging(cfg["hostname"])
    shell.substitute("templates/vmhost/finalize_network.sh", cfg)
    # create initial awall config, but write to final network config
    # the commands should be the same, so double duty is ok here
    shell.append(util.awall.configure(initial_interfaces, cfg["roles"], output_dir, False))
    shell.append("")
    shell.append("rc-service iptables start")
    shell.append("rc-service ip6tables start")
    shell.append("rc-service networking start")
    shell.write_file(output_dir)

    # also add original interface unless
    # DHCP since that will hang boot if it cannot get an IP address
    kept_interfaces = [iface for iface in cfg["interfaces"]
                       if (iface["ipv4_address"] != ["dhcp"])
                       and not iface["ipv6_dhcp"] and (iface["name"] not in names)]

    interfaces = [util.interfaces.loopback()]
    interfaces.extend(cfg["vmhost_interfaces"])
    interfaces.append(util.interfaces.from_config(kept_interfaces))
    interfaces.append(util.interfaces.from_config(cfg["initial_interfaces"]))

    util.file.write("interfaces", "\n".join(interfaces), output_dir)

    util.resolv.create_conf(initial_interfaces, cfg["primary_domain"], cfg["domain"],
                            cfg["local_dns"], cfg["external_dns"], output_dir)


_SETUP_OVS = """echo "Configuring OpenVSwitch"

rc-update add ovs-modules boot
rc-update add ovsdb-server boot
rc-update add ovs-vswitchd boot

echo tun >> /etc/modules

# run now
rc-service ovs-modules start
rc-service ovsdb-server start
rc-service ovs-vswitchd start

modprobe tun

# rc-service networking stop
"""
