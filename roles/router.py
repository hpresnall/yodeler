"""Configuration & setup for a Shorewall based router."""
import os.path
import os
import shutil

import util.file
import util.interfaces
import util.libvirt
import util.shell

import config.vlan

from roles.role import Role


class Router(Role):
    """Router defines the configuration needed to setup a system that can route from the configured
     vlans to the internet"""

    def __init__(self):
        super().__init__("router")

    def additional_configuration(self, cfg):
        # router will use Shorewall & udhcpcd instead
        cfg["local_firewall"] = False
        cfg["remove_packages"].add("dhclient")

    def additional_packages(self):
        return {"shorewall", "shorewall6", "ipset", "radvd",
                "ulogd", "ulogd-json",
                "dhcpcd", "dhcrelay"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        uplink = cfg.get("uplink")

        if uplink is None:
            raise KeyError("router must define an uplink")

        uplink["comment"] = "internet uplink"
        uplink["name"] = "eth0"  # always the first interface on the router
        # IPv6 dhcp managed by udhcpd not ifupdown
        uplink["ipv6_dhcp"] = False

        config.interface.validate_iface(uplink)
        interfaces = [util.interfaces.loopback(), util.interfaces.from_config([uplink])]

        # uplink can be an existing vswitch or a physical iface on the host via macvtap
        if "vswitch" in uplink:
            config.interface.validate_network(uplink, cfg["vswitches"])
            iface = {"vswitch": uplink["vswitch"], "vlan": uplink["vlan"]}
            uplink_xml = util.libvirt.interface_from_config(cfg["hostname"], iface)
        elif "macvtap" in uplink:
            uplink_xml = util.libvirt.macvtap_interface(cfg, uplink["macvtap"])
        else:
            raise KeyError(("invald uplink in router; "
                            "it must define a vswitch+vlan or a macvtap host interface"))

        libvirt_interfaces = [uplink_xml]
        iface_counter = 1
        shorewall = _init_shorewall()

        for vswitch in cfg["vswitches"].values():
            vlan_interfaces = _configure_vlans(vswitch, f"eth{iface_counter}", shorewall)

            if len(vlan_interfaces) > 0:
                iface_counter += 1
                interfaces.extend(vlan_interfaces)
                # new libvirt interface for the vswitch
                libvirt_interfaces.append(util.libvirt.router_interface(cfg['hostname'], vswitch))

        # re-number defined interfaces
        for iface in cfg["interfaces"]:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        # rewrite interfaces with uplink and vswitches / vlans first
        interfaces.append(util.interfaces.from_config(cfg["interfaces"]))
        util.file.write("interfaces", "\n".join(interfaces), output_dir)

        if cfg["is_vm"]:
            util.libvirt.update_interfaces(cfg['hostname'], libvirt_interfaces, output_dir)

        return [_configure_shorewall(cfg, shorewall, output_dir)]


def _configure_vlans(vswitch, iface_name, shorewall):
    vswitch_name = vswitch["name"].upper()
    vlan_interfaces = []
    untagged = False

    for vlan in vswitch["vlans"]:
        if not vlan["routable"]:
            continue

        # $VSWITCH matches shorewall param that defines VSWITCH=ethx
        shorewall_name = "$" + vswitch_name

        if vlan["id"] is None:
            untagged = True
        else:
            shorewall_name += f".{vlan['id']}"  # $VSWITCH.vlan_id

        vlan_name = vlan["name"]
        vlan_interfaces.append(util.interfaces.for_vlan(vlan, iface_name))

        # zone and interface for each vlan
        shorewall["zones"].append(f"{vlan_name}\tipv4")
        shorewall["zones6"].append(f"{vlan_name}\tipv6")

        shorewall["interfaces"].append((f"{vlan_name}\t{shorewall_name}"
                                        "\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"))
        shorewall["interfaces6"].append((f"{vlan_name}\t{shorewall_name}"
                                         "\ttcpflags,dhcp,rpfilter,accept_ra=2"))

        all_access = False

        for access in vlan["access_vlans"]:
            if access == "all":
                all_access = True
                shorewall["policy"].append(f"# vlan {vlan_name} has full access to EVERYTHING")
            else:
                shorewall["policy"].append(f"# vlan {vlan_name} has full access to vlan {access}")
            shorewall["policy"].append(f"{vlan_name}\t{access}\tACCEPT")
            # all should be the only item in the list from validation, so loop will end

        #  all access => internet
        if not all_access and vlan["allow_internet"]:
            shorewall["policy"].append(f"# vlan {vlan_name} has full internet access")
            shorewall["policy"].append(f"{vlan_name}\tinet\tACCEPT")

        # snat only on ipv4; ipv6 will be routable
        shorewall["snat"].append(f"MASQUERADE\t{vlan['ipv4_subnet']}\t$INTERNET")

    interfaces = []

    if len(vlan_interfaces) > 0:
        comment = f"vlans on '{vswitch['name']}' vswitch"

        if untagged:  # interface with no vlan already created by vswitch; just output the comment
            interfaces.append("# " + comment)
        else:  # create parent interface with the comment
            interfaces.append(util.interfaces.port(iface_name, comment))

        # vlan interfaces after the parent
        interfaces.extend(vlan_interfaces)

        # shorewall param to associate vswitch with interface
        shorewall["params"].append(vswitch_name + "=" + iface_name)
    # else no routable interfaces => do not create anything

    return interfaces


def _init_shorewall():
    # dict of shorewall config files; will be appended for each vswitch / vlan
    shorewall = {}
    shorewall["params"] = ["INTERNET=eth0"]
    shorewall["zones"] = ["fw\tfirewall\ninet\tipv4"]
    shorewall["zones6"] = ["fw\tfirewall\ninet\tipv6"]
    shorewall["interfaces"] = [
        "inet\t$INTERNET\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"]
    shorewall["interfaces6"] = ["inet\t$INTERNET\ttcpflags,dhcp,rpfilter,accept_ra=2"]
    shorewall["policy"] = []
    shorewall["snat"] = []

    return shorewall


def _configure_shorewall(cfg, shorewall, output_dir):
    shorewall4 = os.path.join(output_dir, "shorewall")
    shorewall6 = os.path.join(output_dir, "shorewall6")

    os.mkdir(shorewall4)
    os.mkdir(shorewall6)

    params = "\n".join(shorewall["params"])
    util.file.write("params", params, shorewall4)
    util.file.write("params", params, shorewall6)

    util.file.write("zones", "\n".join(shorewall["zones"]), shorewall4)
    util.file.write("zones", "\n".join(shorewall["zones6"]), shorewall6)

    util.file.write("interfaces", "\n".join(shorewall["interfaces"]), shorewall4)
    util.file.write("interfaces", "\n".join(shorewall["interfaces6"]), shorewall6)

    template = """
# drop everything coming in from the internet
inet all DROP    NFLOG({log})

# reject everything else
all all REJECT  NFLOG({log})
"""
    shorewall["policy6"] = list(shorewall["policy"])
    shorewall["policy"].append(template.format(log=4))
    shorewall["policy6"].append(template.format(log=6))

    util.file.write("policy", "\n".join(shorewall["policy"]), shorewall4)
    util.file.write("policy", "\n".join(shorewall["policy6"]), shorewall6)

    util.file.write("snat", "\n".join(shorewall["snat"]), shorewall4)

    # TODO add ability to customize rules
    shutil.copyfile("templates/router/shorewall/rules", os.path.join(shorewall4, "rules"))
    shutil.copyfile("templates/router/shorewall/rules6", os.path.join(shorewall6, "rules"))

    shutil.copy("templates/router/ipsets.save", output_dir)
    shutil.copy("templates/router/ulogd.conf", output_dir)
    shutil.copy("templates/router/ulogd", output_dir)

    # TODO add correct vlan ifaces and DHCP servers to cfg for substitution
    shell = util.shell.ShellScript("shorewall.sh")
    shell.substitute("templates/router/shorewall.sh", cfg)
    shell.write_file(output_dir)

    return shell.name
