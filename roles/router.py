"""Configuration & setup for a Shorewall based router."""
import os.path
import os
import shutil

import util.file
import util.interfaces
import util.libvirt
import util.shell
import util.dhcpcd

from roles.role import Role

import config.interface as interface


class Router(Role):
    """Router defines the configuration needed to setup a system that can route from the configured
     vlans to the internet"""

    def __init__(self, cfg: dict):
        super().__init__("router", cfg)

    def additional_packages(self):
        return {"shorewall", "shorewall6", "ipset", "radvd", "ulogd", "ulogd-json", "dhcrelay", "iptables", "ip6tables"}

    def configure_interfaces(self):
        uplink = interface.configure_uplink(self._cfg)

        # add an interface for each vswitch that has routable vlans
        iface_counter = 1  # start at eth1

        # delegate IPv6 delegated prefixes across all vswitches
        # network for each vlan is in the order they are defined unless vlan['ipv6_pd_network'] is set
        # start at 1 => do not delegate the 0 network
        prefix_counter = 1

        vswitch_interfaces = []

        for vswitch in self._cfg["vswitches"].values():
            # create a unique interface for each vswitch
            if self._cfg["is_vm"]:
                iface_name = f"eth{iface_counter}"
            elif vswitch["uplink"]:
                iface_name = vswitch["uplink"]
                # vswitch validation already confirmed uplink uniqueness
            else:
                # note that this assumes ethernet layout of non-vm hosts
                iface_name = f"eth{iface_counter}"
            iface_counter += 1

            vswitch["router_iface"] = iface_name
            vlan_interfaces = []
            untagged = False

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                if vlan["id"] is None:
                    untagged = True

                vlan_iface = interface.for_vlan(iface_name, vswitch, vlan)
                vlan["router_iface"] = vlan_iface["name"]
                vlan_interfaces.append(vlan_iface)

                # will add a prefix delegation stanza to dhcpcd.conf for the vlan; see dhcpcd.py
                network = vlan["ipv6_pd_network"]
                if not network:
                    network = prefix_counter
                    prefix_counter += 1
                _validate_vlan_pd_network(uplink["ipv6_pd_prefixlen"], network)
                uplink["ipv6_delegated_prefixes"].append(f"{vlan_iface['name']}/{network}")

            if vlan_interfaces:
                # create the parent interface for the vlan interfaces
                comment = f"vlans on '{vswitch['name']}' vswitch"

                if untagged:  # interface with no vlan tag already created; add the comment on the first interface
                    vlan_interfaces[0]["comment"] = comment
                else:  # add the base interface as a port
                    vswitch_interfaces.append(interface.for_port(iface_name, comment))
                vswitch_interfaces.extend(vlan_interfaces)

        if "interfaces" not in self._cfg:
            self._cfg["interfaces"] = []

        # set uplink then vswitch interfaces first in /etc/interfaces
        self._cfg["interfaces"] = [uplink] + vswitch_interfaces + self._cfg["interfaces"]

    def additional_configuration(self):
        # router will use Shorewall instead
        self._cfg["local_firewall"] = False

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        # router needed if there are routable vlans
        for vswitch in site_cfg["vswitches"].values():
            for vlan in vswitch["vlans"]:
                if vlan["routable"]:
                    return 1
        return 0

    def validate(self):
        pass

    def write_config(self, setup, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        uplink = self._cfg["uplink"]

        if self._cfg["is_vm"]:
            # uplink can be an existing vswitch or a physical iface on the host via macvtap
            if "macvtap" in uplink:
                uplink_xml = util.libvirt.macvtap_interface(self._cfg, uplink["macvtap"])
            else:  # use vswitch+vlan
                uplink_xml = util.libvirt.interface_from_config(self._cfg["hostname"], uplink)

            # add an interface to the host's libvirt definition for each vswitch; order matches network_interfaces
            libvirt_interfaces = [uplink_xml]

        shorewall = _init_shorewall()

        radvd_template = util.file.read("templates/router/radvd.conf")
        radvd_config = []

        dhrelay4_ifaces = []
        dhrelay6_ifaces = []

        for vswitch in self._cfg["vswitches"].values():
            routable_vlans = False

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                routable_vlans = True
                _configure_shorewall(shorewall, vswitch["name"], vlan)

                if vlan["dhcp4_enabled"]:
                    dhrelay4_ifaces.append(vlan["router_iface"])

                if not vlan["ipv6_disabled"]:
                    # dhcp_managed== True => AdvManagedFlag on
                    radvd_config.append(radvd_template.format(
                        vlan["router_iface"], "on" if vlan["dhcp6_managed"] else "off"))

                    dhrelay6_ifaces.append(vlan["router_iface"])

            if routable_vlans:
                # shorewall param to associate vswitch with interface
                shorewall["params"].append(vswitch["name"].upper() + "=" + vswitch["router_iface"])

                if self._cfg["is_vm"]:
                    # new libvirt interface to trunk the vlans
                    libvirt_interfaces.append(util.libvirt.router_interface(self._cfg['hostname'], vswitch))

        if self._cfg["is_vm"]:
            util.libvirt.update_interfaces(self._cfg['hostname'], libvirt_interfaces, output_dir)

        if radvd_config:
            util.file.write("radvd.conf", "\n".join(radvd_config), output_dir)

            setup.service("radvd", "boot")
            setup.append("rootinstall radvd.conf /etc")

        _write_dhcrelay_config(self._cfg, setup, dhrelay4_ifaces, dhrelay6_ifaces)
        _write_shorewall_config(self._cfg, shorewall, setup, output_dir)


def _validate_vlan_pd_network(prefixlen: int, ipv6_pd_network: int):
    if ipv6_pd_network is not None:
        maxnetworks = 2 ** (64 - prefixlen)
        if ipv6_pd_network >= maxnetworks:
            raise KeyError((f"pd network {ipv6_pd_network} is larger than the {maxnetworks} " +
                            f" networks available with the 'ipv6_pd_prefixlen' of {prefixlen}"))


def _write_dhcrelay_config(cfg, setup, dhrelay4_ifaces, dhrelay6_ifaces):
    dhcp_server = cfg["hosts"][cfg["roles_to_hostnames"]["dhcp"][0]]
    dhcp_addresses = interface.find_ips_to_interfaces(cfg, dhcp_server["interfaces"], first_match_only=False)

    if not dhcp_addresses:
        raise ValueError("router needs to relay DHCP but cannot find any reachable DHCP servers")

    dhcp_addresses = dhcp_addresses[0]

    # dhrelay requires setting the upper interface _and_ ipaddress
    # find the router interface that is in the same subnet as the dhcp server
    upper_iface4 = None
    upper_iface6 = None

    for iface in cfg["interfaces"]:
        if iface["type"] != "vlan":
            continue

        if dhcp_addresses["ipv4_address"] in iface["vlan"]["ipv4_subnet"]:
            upper_iface4 = iface["name"]
        if ((iface["vlan"]["ipv6_subnet"] is not None)
                and (dhcp_addresses["ipv6_address"] in iface["vlan"]["ipv6_subnet"])):
            upper_iface6 = iface["name"]

    if dhrelay4_ifaces or dhrelay6_ifaces:
        setup.blank()
        setup.comment("configure dhcp relay for routable vlans")

    if dhrelay6_ifaces:
        if not dhcp_addresses["ipv6_address"]:
            raise ValueError("router needs to relay DHCP but cannot find any reachable IPv6 addresses")

        setup.append(util.file.read("templates/router/dhcrelay6.sh"))

    if dhrelay4_ifaces:
        if not dhcp_addresses["ipv4_address"]:
            raise ValueError("router needs to relay DHCP but cannot find any reachable IPv4 addresses")

        # dhrelay requires listening on the interface that is on the dhcp server's vlan
        # make sure it is setup, even if that vlan does not have dhcp enabled
        if upper_iface4 not in dhrelay4_ifaces:
            dhrelay4_ifaces.insert(0, upper_iface4)

        setup.comment("setup dhcrelay.conf")
        setup.append("echo 'IFACE=\"" + " ".join(dhrelay4_ifaces) + "\"' >> /etc/conf.d/dhcrelay")
        setup.append("echo 'DHCRELAY_SERVERS=\"" +
                     str(dhcp_addresses["ipv4_address"]) + "\"' >> /etc/conf.d/dhcrelay")
        setup.service("dhcrelay")
        setup.blank()

    if dhrelay6_ifaces:
        # remove upper iface from list; no need to relay traffic already being broadcast
        # dhrelay6 does require it to be explicitly set with the ip address
        dhrelay6_ifaces = [iface for iface in dhrelay6_ifaces if iface != upper_iface6]

        setup.comment("setup dhcrelay6.conf")
        setup.append("echo 'IFACE=\"" + " ".join(dhrelay6_ifaces) + "\"' >> /etc/conf.d/dhcrelay6")
        setup.append("echo 'DHCRELAY_SERVERS=\"-u " +
                     str(dhcp_addresses["ipv6_address"]) + "%" + upper_iface6 + "\"' >> /etc/conf.d/dhcrelay6")
        setup.service("dhcrelay6")
        setup.blank()


def _init_shorewall():
    # dict of shorewall config files; will be appended for each vswitch / vlan
    shorewall = {}
    shorewall["params"] = ["INTERNET=eth0"]
    shorewall["zones"] = ["fw\tfirewall\ninet\tipv4"]
    shorewall["zones6"] = ["fw\tfirewall\ninet\tipv6"]
    shorewall["interfaces"] = ["inet\t$INTERNET\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"]
    shorewall["interfaces6"] = ["inet\t$INTERNET\ttcpflags,dhcp,rpfilter,accept_ra=2"]
    shorewall["policy"] = []
    shorewall["snat"] = []

    return shorewall


def _configure_shorewall(shorewall, vswitch_name, vlan):
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


def _write_shorewall_config(cfg, shorewall, setup, output_dir):
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
inet all DROP    NFLOG({0})

# reject everything else
all all REJECT  NFLOG({0})
"""
    shorewall["policy6"] = list(shorewall["policy"])
    shorewall["policy"].append(template.format(4))
    shorewall["policy6"].append(template.format(6))

    util.file.write("policy", "\n".join(shorewall["policy"]), shorewall4)
    util.file.write("policy", "\n".join(shorewall["policy6"]), shorewall6)

    util.file.write("snat", "\n".join(shorewall["snat"]), shorewall4)

    # TODO add ability to customize rules
    shutil.copyfile("templates/router/shorewall/rules", os.path.join(shorewall4, "rules"))
    shutil.copyfile("templates/router/shorewall/rules6", os.path.join(shorewall6, "rules"))

    shutil.copy("templates/router/ulogd.conf", output_dir)
    shutil.copy("templates/router/ulogd", output_dir)

    # TODO add correct vlan ifaces and DHCP servers to cfg for substitution

    setup.comment("# shorewall config")
    setup.substitute("templates/router/shorewall.sh", cfg)
