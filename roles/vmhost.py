"""Configuration & setup for the main KVM & Openvswitch Alpine host."""
import os.path
import xml.etree.ElementTree as xml
import shutil
import ipaddress

import util.shell
import util.file
import util.interfaces
import util.awall
import util.resolv

from roles.role import Role


class VmHost(Role):
    """VmHost defines the configuration needed to setup a KVM host using OpenVswitch."""

    def __init__(self):
        super().__init__("vmhost")

    def additional_packages(self):
        return {"python3", "openvswitch", "qemu-system-x86_64", "qemu-img",
                "libvirt", "libvirt-daemon", "libvirt-qemu", "dbus", "polkit", "git"}

    def additional_ifaces(self, cfg):
        return []

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        scripts = []

        scripts.append(_setup_open_vswitch(cfg, output_dir))
        scripts.append(_setup_libvirt(cfg, output_dir))

        # libvirt cannot be started by locald, so create a 2nd locald script
        # for doing the rest of the config
        _configure_libvirt(cfg, output_dir)

        # patch alpine-make-vm-image to use apk_cache
        shutil.copyfile("templates/vmhost/cache.patch", os.path.join(output_dir, "cache.patch"))

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
        iface = util.interfaces.create_port(vswitch_name)
        iface["comment"] = "vswitch"
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
            iface = util.interfaces.create_port(uplink)
            iface["comment"] = "uplink for vswitch " + vswitch_name
            uplink_interfaces.append(iface)
    else:
        shell.append(f"ovs-vsctl add-port {vswitch_name} {uplink}")
        iface = util.interfaces.create_port(uplink)
        iface["comment"] = "uplink for vswitch " + vswitch_name
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
    util.file.write("interfaces",
                    util.interfaces.as_etc_network(cfg["vmhost_interfaces"] + cfg["interfaces"]),
                    output_dir)

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
        template = xml.parse("templates/vm/network.xml")
        net = template.getroot()

        name = net.find("name")
        name.text = vswitch["name"]

        bridge = net.find("bridge")
        bridge.attrib["name"] = vswitch["name"]

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
        network_xml = name.text + ".xml"
        template.write(os.path.join(output_dir, network_xml))

        shell.append(f"virsh net-define $DIR/{network_xml}")
        shell.append(f"virsh net-start {name.text}")
        shell.append(f"virsh net-autostart {name.text}")
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

        if "vswitch" in iface:
            vswitches = cfg["vswitches"]
        else:
            vswitches = _configure_initial_iface(i, iface)

        iface["firewall_zone"] = "initial_" + iface["name"]

        util.interfaces.validate(iface, vswitches)

    # script to switch network to final configuration
    # run before adding to initial_interfaces since vswitches & uplinks do no need firewalling
    shell = util.shell.ShellScript("finalize_network.sh")
    shell.append_self_dir()
    shell.append_rootinstall()
    shell.setup_logging(cfg["hostname"])
    shell.substitute("templates/vmhost/finalize_network.sh", cfg)
    shell.append(util.awall.configure(initial_interfaces, output_dir, False))
    shell.append("")
    shell.append("rc-service iptables start")
    shell.append("rc-service ip6tables start")
    shell.append("rc-service networking start")
    shell.write_file(output_dir)

    # also add original interface unless
    # DHCP since that will hang boot if it cannot get an IP address
    # initial interface will be reused
    initial_interfaces += [iface for iface in cfg["vmhost_interfaces"]
                           if (iface["ipv4_method"] != ["dhcp"])
                           and not iface["ipv6_dhcp"] and (iface["name"] not in names)]

    util.file.write("interfaces", util.interfaces.as_etc_network(initial_interfaces), output_dir)

    util.resolv.create_conf(initial_interfaces, cfg["primary_domain"], cfg["domain"],
                            cfg["local_dns"], cfg["external_dns"], output_dir)


def _configure_initial_iface(i, iface):
    """Finalize configuration so validation will pass.

    For initial_interfaces, allow:
    1) interfaces to be defined without a vswitch or vlan
    2) static ip addresses in a subnet not on any vlan

    To pass util.interfaces.validate(), create a fake vswitch and vlan.
    """
    initial_vswitch = {"name": "initial"}
    vswitches = {"initial": initial_vswitch}
    initial_vlan = {"name": "initial", "ipv6_disable": False}

    # no vlan => cannot lookup subnet so it must be defined explicitly
    if "ipv4_address" in iface:
        if iface["ipv4_address"] != 'dhcp':
            if "ipv4_subnet" not in iface:
                raise KeyError(("ipv4_subnet must be set "
                                f"when using static ipv4_address on interface {i}: {iface}"))
            try:
                initial_vlan["ipv4_subnet"] = ipaddress.ip_network(iface["ipv4_subnet"])
            except:
                raise KeyError(f"invalid ipv4_subnet defined for interface {i}: {iface}")
    # else util.interface.validate() handles None

    if "ipv6_address" in iface:
        if "ipv6_subnet" not in iface:
            raise KeyError(("ipv6_subnet must be set "
                            f"when using static ipv6_address on interface {i}: {iface}"))

        try:
            initial_vlan["ipv6_subnet"] = ipaddress.ip_network(iface["ipv6_subnet"])
        except:
            raise KeyError(f"invalid ipv6_subnet defined for interface {i}: {iface}")
    # else util.interface.validate() handles None

    initial_vlan["id"] = iface.get("vlan")  # None case handled in util.interfaces.validate()
    initial_vlan["default"] = True
    initial_vswitch["vlans_by_id"] = {initial_vlan["id"]: initial_vlan}
    initial_vswitch["vlans_by_name"] = {initial_vlan["name"]: initial_vlan}
    initial_vswitch["default_vlan"] = initial_vlan

    iface["vswitch"] = initial_vswitch["name"]

    return vswitches


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
