import os.path
import xml.etree.ElementTree as xml
import shutil

import util.shell
import util.file

packages = {"python3", "openvswitch", "qemu-system-x86_64", "qemu-img",
            "libvirt", "libvirt-daemon", "libvirt-qemu", "dbus", "polkit", "git"}


def setup(cfg, dir):
    scripts = []

    scripts.append(_setup_open_vswitch(cfg, dir))
    scripts.append(_setup_libvirt(cfg, dir))

    # create bootstrap wrapper script and setup script for locald
    # these are _separate_ from setup
    bootstrap = util.shell.ShellScript("bootstrap.sh")
    bootstrap.append_self_dir()
    bootstrap.append(util.file.substitute("templates/vmhost/bootstrap.sh", cfg))
    bootstrap.write_file(dir)

    # create local.d file that runs setup on first reboot after Alpine install
    setup = util.shell.ShellScript("setup.start")
    setup.append(util.file.substitute("templates/vmhost/locald_setup.sh", cfg))
    setup.write_file(dir)

    # libvirt cannot be started by locald, so create a 2nd locald script
    # for doing the rest of the config
    _configure_libvirt(cfg, dir)

    shutil.copyfile("templates/vmhost/cache.patch", os.path.join(dir, "cache.patch"))

    return scripts


def _setup_open_vswitch(cfg, dir):
    shell = util.shell.ShellScript("openvswitch.sh")
    shell.append(_setup_ovs)

    # create new entries in /etc/network/interfaces for each switch
    new_interfaces = ""

    # create Open Vswitches for each vswitch configuration
    # add uplink ports with correct tagging where specified
    for vswitch in cfg["vswitches"].values():
        vswitch_name = vswitch["name"]
        shell.append(f"# setup {vswitch_name} vswitch")
        shell.append(f"ovs-vsctl add-br {vswitch_name}")

        # ensure switch iface is configured
        new_interfaces += _vswitch_iface_template.format(vswitch_name)

        uplink = vswitch["uplink"]
        if uplink is None:
            shell.append("")
            continue
        elif not isinstance(uplink, str):
            bond_ifaces = " ".join(uplink)
            shell.append(f"ovs-vsctl add-bond {vswitch_name} uplink {bond_ifaces} lacp=active")

            for iface in uplink:
                # ensure physical uplink ifaces are configured
                new_interfaces += _vswitch_iface_template.format(iface)

            uplink = "uplink"
        else:
            shell.append(f"ovs-vsctl add-port {vswitch_name} {uplink}")
            # ensure physical uplink iface is configured
            new_interfaces += _vswitch_iface_template.format(uplink)

        vlans_by_id = vswitch["vlans_by_id"].keys()
        if len(vlans_by_id) == 1:
            # single vlan with id => access port
            if None not in vlans_by_id:
                shell.append(f"ovs-vsctl set port {uplink} tag={trunks[0]}")
                shell.append(f"ovs-vsctl set port {uplink} vlan_mode=access")
            # else no tagging needed
        elif len(vlans_by_id) > 1:  # trunk all vlans
            trunks = [str(vlan_id) for vlan_id in vswitch["vlans_by_id"].keys() if vlan_id != "None"]
            trunks = ",".join(trunks)
            shell.append(f"ovs-vsctl set port {uplink} trunks={trunks}")

            # native or PVID vlan => native_untagged
            # see http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt
            if None in vlans_by_id:
                shell.append(f"ovs-vsctl set port {uplink} vlan_mode=native_untagged")
            else:
                shell.append(f"ovs-vsctl set port {uplink} vlan_mode=trunk")

        shell.append("")

    if cfg["local_firewall"]:
        # replace existing interfaces with new vswitch port names
        awall_base = util.file.read("awall/base.json", dir)

    # replace existing interfaces with new vswitch port names
    interfaces = util.file.read("interfaces", dir)

    for iface in cfg["interfaces"]:
        vswitch_name = iface["vswitch"]["name"]
        port = f"{cfg['hostname']}-{vswitch_name}"

        # fix existing interface name
        interfaces = interfaces.replace(iface["name"], port)

        if cfg["local_firewall"]:
            awall_base = awall_base.replace(iface["name"], port)

        shell.append(f"# setup switch port for interface on vswitch {vswitch_name}")
        shell.append(f"ovs-vsctl add-port {vswitch_name} {port} -- set interface {port} type=internal")

        if iface["vlan"]["id"] is not None:
            shell.append(f"ovs-vsctl set port {port} tag={iface['vlan']['id']}")
            shell.append(f"ovs-vsctl set port {port} vlan_mode=access")

        shell.append("")
    shell.write_file(dir)

    # overwrite the original interfaces file from common setup
    # switch ifaces first so they are up before the host's ports
    util.file.write("interfaces", new_interfaces + interfaces, dir)

    # overwrite the original awall base config
    if cfg["local_firewall"]:
        util.file.write("awall/base.json", awall_base, dir)

    return shell.name


def _setup_libvirt(cfg, dir):
    shell = util.shell.ShellScript("libvirt.sh")
    shell.append(util.file.substitute("templates/vmhost/libvirt.sh", cfg))
    shell.write_file(dir)

    return shell.name


def _configure_libvirt(cfg, dir):
    shell = util.shell.ShellScript("libvirt.start")
    shell.append(util.file.substitute("templates/vmhost/locald_libvirt.sh", cfg))

    # for each vswitch, create an XML network definition
    shell.append("# create all networks")
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
            id = vlan["id"]

            if vlan["default"]:
                portgroup.attrib["default"] = "yes"

            if id is not None:
                v = xml.SubElement(portgroup, "vlan")
                tag = xml.SubElement(v, "tag")
                tag.attrib["id"] = str(id)

            # add to router portgroup
            if vlan["routable"]:
                routable = True
                tag = xml.SubElement(router, "tag")

                if id is None:
                    tag.attrib["id"] = "0"  # id required; use 0 for untagged
                    tag.attrib["nativeMode"] = "untagged"
                else:
                    tag.attrib["id"] = str(id)

        # no routable vlans on the vswitch, remove the router portgroup
        if not routable:
            net.remove(router_portgroup)

        # save the file and add the virsh commands to the script
        network_xml = name.text + ".xml"
        template.write(os.path.join(dir, network_xml))

        shell.append(f"virsh net-define $DIR/{network_xml}")
        shell.append(f"virsh net-start {name.text}")
        shell.append(f"virsh net-autostart {name.text}")
        shell.append("")

    shell.append("# remove from local.d so setup is only run once")
    shell.append("rm $0")

    shell.write_file(dir)

    return shell.name


_setup_ovs = """echo "Configuring OpenVSwitch"

rc-update add ovs-modules boot
rc-update add ovsdb-server boot
rc-update add ovs-vswitchd boot

echo tun >> /etc/modules

# run now
rc-service ovs-modules start
rc-service ovsdb-server start
rc-service ovs-vswitchd start

modprobe tun

#rc-service networking stop
"""

# interface definition for vswitch itself
# set 0 ipv4 address and disable ipv6 router advertisements
_vswitch_iface_template = """auto {0}
iface {0} inet manual
  up ifconfig {0} 0.0.0.0 up
  down ifconfig {0} down
iface {0} inet6 auto
  accept_ra 0

"""
