"""Configuration & setup for a Shorewall based router."""
import os.path
import os
import shutil

import util.file
import util.interfaces
import util.libvirt
import util.shell
import util.dhcpcd

import config.vlan

from roles.role import Role


class Router(Role):
    """Router defines the configuration needed to setup a system that can route from the configured
     vlans to the internet"""

    def __init__(self):
        super().__init__("router")

    def additional_configuration(self, cfg):
        # router will use Shorewall instead
        cfg["local_firewall"] = False

        _configure_uplink(cfg)

    def additional_packages(self, cfg):
        return {"shorewall", "shorewall6", "ipset", "radvd", "ulogd", "ulogd-json", "dhcrelay", "iptables", "ip6tables"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        uplink = cfg["uplink"]

        if cfg["is_vm"]:
            # uplink can be an existing vswitch or a physical iface on the host via macvtap
            if "vswitch" in uplink:
                iface = {"vswitch": uplink["vswitch"], "vlan": uplink["vlan"]}
                uplink_xml = util.libvirt.interface_from_config(cfg["hostname"], iface)
            else:  # macvtap
                uplink_xml = util.libvirt.macvtap_interface(cfg, uplink["macvtap"])

            # add an interface to the host's libvirt definition for each vswitch; order matches network_interfaces
            libvirt_interfaces = [uplink_xml]

        # add interfaces for each vswitch that has routable vlans
        iface_counter = 1  # start at eth1
        new_interfaces = []

        shorewall = _init_shorewall()

        # delegate IPv6 delegated prefixes across all switches
        # network for each vlan is in the order they are defined unless vlan['ipv6_pd_network'] is set
        # start at 1 => do not delegate the 0 network
        delegated_prefixes = []
        prefix_counter = 1

        radvd_template = util.file.read("templates/router/radvd.conf")
        radvd_config = []

        for vswitch in cfg["vswitches"].values():
            iface_name = f"eth{iface_counter}"

            vlan_interfaces = []
            untagged = False

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                if vlan["id"] is None:
                    untagged = True

                vlan_interfaces.append(util.interfaces.for_vlan(vlan, iface_name))
                _configure_shorwall(shorewall, vswitch["name"], vlan)
                vlan_iface = f"{iface_name}.{vlan['id']}"

                # will add a prefix delegation stanza to dhcpcd.conf for the vlan; see dhcpcd.py
                network = vlan["ipv6_pd_network"]
                if not network:
                    network = prefix_counter
                    prefix_counter += 1
                _validate_vlan_pd_network(uplink["ipv6_pd_prefixlen"], network)
                delegated_prefixes.append(f"{vlan_iface}/{network}")

                # AdvManagedFlag
                radvd_config.append(radvd_template.format(vlan_iface, "on" if vlan["dhcp6_managed"] else "off"))

            if len(vlan_interfaces) > 0:
                # create the parent interface for the vlan interfaces
                comment = f"vlans on '{vswitch['name']}' vswitch"

                if untagged:  # interface with no vlan tag already created; just output the comment
                    vlan_interfaces.insert(0, "# " + comment)
                else:  # create parent interface with the comment as the first in the list
                    vlan_interfaces.insert(0, util.interfaces.port(iface_name, None, comment))

                # shorewall param to associate vswitch with interface
                shorewall["params"].append(vswitch["name"].upper() + "=" + iface_name)

                if cfg["is_vm"]:
                    # new libvirt interface to trunk the vlans
                    libvirt_interfaces.append(util.libvirt.router_interface(cfg['hostname'], vswitch))

                new_interfaces.extend(vlan_interfaces)
                iface_counter += 1
            # else no routable vlans, no need to create any matching libvirt interface
        # end for all vswitches

        # re-number config defined interfaces and make uplink (eth0) first
        # TODO explicitly defined interfaces should not be renumbered or used for vlans; need to mark in config/interface.py
        for iface in cfg["interfaces"]:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        uplink["ipv6_delegated_prefixes"] = delegated_prefixes
        cfg["interfaces"].insert(0, uplink)

        # recreate the interfaces file; loopback and uplink first
        interfaces = [util.interfaces.loopback(), util.interfaces.from_config(cfg["interfaces"]), *new_interfaces]
        util.file.write("interfaces", "\n".join(interfaces), output_dir)

        # create dhcpcd.conf with the uplink and prefix delegations
        util.dhcpcd.create_conf(cfg, output_dir)

        if cfg["is_vm"]:
            util.libvirt.update_interfaces(cfg['hostname'], libvirt_interfaces, output_dir)

        util.file.write("radvd.conf", "\n".join(radvd_config), output_dir)

        return [_write_shorewall_config(cfg, shorewall, output_dir)]


def _configure_uplink(cfg):
    # create interface definition for uplink
    uplink = cfg.get("uplink")

    if uplink is None:
        raise KeyError("router must define an uplink")

    # allow some end user configuration of the uplink interface YAML
    # but it will always be eth0 and allow forwarding
    uplink["comment"] = "internet uplink"
    uplink["name"] = "eth0"  # always the first interface on the router
    uplink["forward"] = True
    config.interface.validate_iface(uplink)

    if cfg["is_vm"]:
        # uplink can be an existing vswitch or a physical iface on the host via macvtap
        if "vswitch" in uplink:
            config.interface.validate_network(uplink, cfg["vswitches"])
        elif "macvtap" not in uplink:
            uplink["vswitch"] = None
            raise KeyError(("invald uplink in router; it must define a vswitch+vlan or a macvtap host interface"))

    prefixlen = uplink.get("ipv6_pd_prefixlen")

    if prefixlen is None:
        uplink["ipv6_pd_prefixlen"] = 56
    elif not isinstance(prefixlen, int):
        raise KeyError(f"ipv6_pd_prefixlen {prefixlen} must be an integer")
    elif prefixlen >= 64:
        raise KeyError(f"ipv6_pd_prefixlen {prefixlen} must be < 64")
    elif prefixlen < 48:
        raise KeyError(f"ipv6_pd_prefixlen {prefixlen} must be >= 48")

    return uplink


def _validate_vlan_pd_network(prefixlen: int, ipv6_pd_network: int):
    if ipv6_pd_network is not None:
        maxnetworks = 2 ** (64 - prefixlen)
        if ipv6_pd_network >= maxnetworks:
            raise KeyError((f"pd network {ipv6_pd_network} is larger than the {maxnetworks} " +
                            f" networks available with the 'ipv6_pd_prefixlen' of {prefixlen}"))


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


def _configure_shorwall(shorewall, vswitch_name, vlan):
    vlan_name = vlan["name"]

    # $VSWITCH matches shorewall param that defines <VSWITCH_NAME>=ethx
    shorewall_name = "$" + vswitch_name.upper()

    if vlan["id"] is not None:
        shorewall_name += f".{vlan['id']}"  # $VSWITCH.vlan_id

    # zone and interface for each vlan
    shorewall["zones"].append(f"{vlan_name}\tipv4")
    shorewall["zones6"].append(f"{vlan_name}\tipv6")

    shorewall["interfaces"].append((f"{vlan_name}\t{shorewall_name}\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"))
    shorewall["interfaces6"].append((f"{vlan_name}\t{shorewall_name}\ttcpflags,dhcp,rpfilter,accept_ra=2"))

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


def _write_shorewall_config(cfg, shorewall, output_dir):
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
