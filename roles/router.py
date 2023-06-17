"""Configuration & setup for a Shorewall based router."""
import os.path
import os
import shutil

import util.file as file
import util.interfaces
import util.libvirt
import util.shell
import util.dhcpcd

from roles.role import Role

import config.interface as interface

import util.parse as parse


class Router(Role):
    """Router defines the configuration needed to setup a system that can route from the configured
     vlans to the internet"""

    def additional_packages(self):
        return {"shorewall", "shorewall6", "ipset", "radvd", "ulogd", "ulogd-json", "dhcrelay"}

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
                iface_counter += 1
            elif vswitch["uplinks"]:
                # TODO handle multiple uplinks; maybe just error instead of creating physical bond ifaces
                # TODO if site also has a separate, physical vmhost, then need a way to
                # differentiate uplinks for vmhost vs router; maybe router_iface in vswitch config?
                iface_name = vswitch["uplinks"][0] # next(iter(vswitch["uplinks"]))
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
                if network is None:
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

        # set uplink then vswitch interfaces first in /etc/interfaces
        self._cfg["interfaces"] = [uplink] + vswitch_interfaces + self._cfg.setdefault("interfaces", [])

    def additional_configuration(self):
        # router will use Shorewall instead
        self._cfg["local_firewall"] = False

        self.add_alias("gateway")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        # router needed if there are routable vlans
        for vswitch in site_cfg["vswitches"].values():
            for vlan in vswitch["vlans"]:
                if vlan["routable"]:
                    return 1
        return 0

    def validate(self):
        routable_vlans = False
        for vswitch in self._cfg["vswitches"].values():
            for vlan in vswitch["vlans"]:
                if vlan["routable"]:
                    routable_vlans = True
        if not routable_vlans:
            raise ValueError("router not needed if there are no routable vlans")

    def write_config(self, setup: util.shell.ShellScript, output_dir: str):
        """Create the scripts and configuration files for the given host's configuration."""
        uplink = parse.non_empty_dict("router 'uplink'", self._cfg.get("uplink"))

        libvirt_interfaces = []

        if self._cfg["is_vm"]:
            # uplink can be an existing vswitch or a physical iface on the host via macvtap
            if "macvtap" in uplink:
                uplink_xml = util.libvirt.macvtap_interface(self._cfg, uplink["macvtap"])
            else:  # use vswitch+vlan
                uplink_xml = util.libvirt.interface_from_config(self._cfg["hostname"], uplink)

            # add an interface to the host's libvirt definition for each vswitch; order matches network_interfaces
            libvirt_interfaces = [uplink_xml]

        shorewall = _init_shorewall(self._cfg)

        routable_vlans = []

        radvd_template = file.read("templates/router/radvd.conf")
        radvd_config = []

        dhrelay4_ifaces = []
        dhrelay6_ifaces = []

        for vswitch in self._cfg["vswitches"].values():
            has_routable_vlans = False

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                has_routable_vlans = True
                routable_vlans.append(vlan)

                _configure_shorewall_vlan(shorewall, vswitch["name"], vlan)

                if vlan["dhcp4_enabled"]:
                    dhrelay4_ifaces.append(vlan["router_iface"])

                if not vlan["ipv6_disabled"]:
                    # dhcp_managed== True => AdvManagedFlag on
                    radvd_config.append(radvd_template.format(
                        vlan["router_iface"], "on" if vlan["dhcp6_managed"] else "off"))

                    dhrelay6_ifaces.append(vlan["router_iface"])

            if has_routable_vlans:
                # shorewall param to associate vswitch with interface
                param = vswitch["name"].upper() + "=" + vswitch["router_iface"]
                shorewall["params"].append(param)
                shorewall["params6"].append(param)

                if self._cfg["is_vm"]:
                    # new libvirt interface to trunk the vlans
                    libvirt_interfaces.append(util.libvirt.router_interface(self._cfg['hostname'], vswitch))

        # blank line after vlan to firewall ping rules
        shorewall["rules"].append("")
        shorewall["rules6"].append("")

        if self._cfg["is_vm"]:
            util.libvirt.update_interfaces(self._cfg['hostname'], libvirt_interfaces, output_dir)

        if radvd_config:
            file.write("radvd.conf", "\n".join(radvd_config), output_dir)

            setup.service("radvd", "boot")
            setup.append("rootinstall radvd.conf /etc")

        _configure_shorewall_rules(self._cfg, shorewall, routable_vlans)
        _write_dhcrelay_config(self._cfg, setup, dhrelay4_ifaces, dhrelay6_ifaces, shorewall)
        _write_shorewall_config(self._cfg, shorewall, setup, output_dir)


def _validate_vlan_pd_network(prefixlen: int, ipv6_pd_network: int):
    if ipv6_pd_network is not None:
        maxnetworks = 2 ** (64 - prefixlen)
        if ipv6_pd_network >= maxnetworks:
            raise KeyError((f"pd network {ipv6_pd_network} is larger than the {maxnetworks} " +
                            f" networks available with the 'ipv6_pd_prefixlen' of {prefixlen}"))


def _write_dhcrelay_config(cfg: dict, setup: util.shell.ShellScript, dhrelay4_ifaces: list, dhrelay6_ifaces: list, shorewall: dict):
    dhcp_server = cfg["hosts"][cfg["roles_to_hostnames"]["dhcp"][0]]
    dhcp_addresses = interface.find_ips_to_interfaces(cfg, dhcp_server["interfaces"], first_match_only=False)

    if not dhcp_addresses:
        raise ValueError("router needs to relay DHCP but cannot find any reachable DHCP servers")

    # assume only one dhcp server
    dhcp_addresses = dhcp_addresses[0]

    # no need to relay if DHCP is local
    if str(dhcp_addresses["ipv4_address"]) == "127.0.0.1":
        dhrelay4_ifaces = []
    if str(dhcp_addresses["ipv6_address"]) == "::1":
        dhrelay6_ifaces = []

    if dhrelay4_ifaces or dhrelay6_ifaces:
        setup.blank()
        setup.comment("configure dhcp relay for routable vlans")

    if dhrelay6_ifaces:
        # create dhcrelay6 init.d first, then ipv4 conf, then ipv6 conf
        if not dhcp_addresses["ipv6_address"]:
            raise ValueError("router needs to relay DHCP but cannot find any reachable IPv6 addresses")

        setup.append(file.read("templates/router/dhcrelay6.sh"))

    if dhrelay4_ifaces:
        if not dhcp_addresses["ipv4_address"]:
            raise ValueError("router needs to relay DHCP but cannot find any reachable IPv4 addresses")

        # find the router interface that is in the same subnet as the dhcp server
        upper_iface4 = dhcp_addresses["src_iface"]["name"] if dhcp_addresses["ipv4_address"] else None

        # dhrelay requires listening on the interface that is on the dhcp server's vlan
        # make sure it is setup, even if that vlan does not have dhcp enabled
        if upper_iface4 and upper_iface4 not in dhrelay4_ifaces:
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
        upper_iface6 = dhcp_addresses["src_iface"]["name"] if dhcp_addresses["ipv6_address"] else ""
        dhrelay6_ifaces = [iface for iface in dhrelay6_ifaces if iface != upper_iface6]
        upper_iface6 = "%" + upper_iface6 if upper_iface6 else upper_iface6

        setup.comment("setup dhcrelay6.conf")
        setup.append("echo 'IFACE=\"" + " ".join(dhrelay6_ifaces) + "\"' >> /etc/conf.d/dhcrelay6")
        setup.append("echo 'DHCRELAY_SERVERS=\"-u " +
                     str(dhcp_addresses["ipv6_address"]) + upper_iface6 + "\"' >> /etc/conf.d/dhcrelay6")
        setup.service("dhcrelay6")
        setup.blank()


def _init_shorewall(cfg: dict):
    # dict of shorewall config files; will be appended for each vswitch / vlan
    shorewall = {}
    shorewall["params"] = ["INTERNET=" + cfg["uplink"]["name"]]
    shorewall["params6"] = ["INTERNET=" + cfg["uplink"]["name"]]
    shorewall["zones"] = ["fw\tfirewall\ninet\tipv4"]
    shorewall["zones6"] = ["fw\tfirewall\ninet\tipv6"]
    shorewall["interfaces"] = ["inet\t$INTERNET\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"]
    shorewall["interfaces6"] = ["inet\t$INTERNET\ttcpflags,dhcp,rpfilter,accept_ra=2"]
    shorewall["policy"] = []
    shorewall["snat"] = []
    shorewall["rules"] = [file.read("templates/router/shorewall/rules")]
    shorewall["rules6"] = [file.read("templates/router/shorewall/rules6")]

    return shorewall


def _configure_shorewall_vlan(shorewall, vswitch_name, vlan):
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
            shorewall["policy"].append(f"# {vlan_name} vlan has full access to EVERYTHING")
        else:
            shorewall["policy"].append(f"# {vlan_name} vlan has full access to vlan {access}")
        shorewall["policy"].append(f"{vlan_name}\t{access}\tACCEPT")
        shorewall["policy"].append("")
        # all should be the only item in the list from validation, so loop will end

    #  all access => internet
    if not all_access and vlan["allow_internet"]:
        shorewall["policy"].append(f"# {vlan_name} vlan has full internet access")
        shorewall["policy"].append(f"{vlan_name}\tinet\tACCEPT")
        shorewall["policy"].append("")

    shorewall["rules"].append(f"Ping(ACCEPT)\t{vlan_name}\t$FW")
    shorewall["rules6"].append(f"Ping(ACCEPT)\t{vlan_name}\t$FW")

    # snat only on ipv4; ipv6 will be routable
    shorewall["snat"].append(f"MASQUERADE\t{vlan['ipv4_subnet']}\t$INTERNET")


def _configure_shorewall_rules(cfg: dict, shorewall: dict, routable_vlans: list[dict]):
    # add a rule for each host role so other vlans can acess that host
    for host in cfg["hosts"].values():
        if len(host["roles"]) < 2:
            continue

        # only comment once in rules and add param
        output4 = False
        output6 = False

        for iface in host["interfaces"]:
            if (iface["type"] not in {"std", "vlan"}) or (not iface["vlan"]["routable"]):
                continue

            vlan_name = iface["vlan"]["name"]
            host_roles = [role.name for role in host["roles"] if role != "common"]

            # add param for host's ip address
            param = (host["hostname"] + "_" + vlan_name).upper()
            param4 = param6 = None
            if iface["ipv4_address"] != "dhcp":
                param4 = f"{vlan_name}:{iface['ipv4_address']}"
            if iface["ipv6_address"]:
                param6 = f"{vlan_name}:{iface['ipv6_address']}"

            for routable_vlan in routable_vlans:
                if routable_vlan["name"] == vlan_name:
                    continue  # no rule needed for same vlan

                # no need for more specific rule if vlan can already access this host
                access_vlans = routable_vlan["access_vlans"]
                if (routable_vlan["name"] in access_vlans) or ("all" in access_vlans):
                    continue

                if param4:
                    if not output4:
                        output4 = True
                        shorewall["params"].append(f"{param}={param4}")
                        shorewall["rules"].append(f"# allow access to host {host['hostname']}")

                    # allow ping on all hosts
                    shorewall["rules"].append(f"Ping(ACCEPT)\t{routable_vlan['name']}\t${param}")

                    for role in host_roles:
                        if (role == "dns"):
                            shorewall["rules"].append(f"DNS(ACCEPT)\t{routable_vlan['name']}\t${param}")
                            shorewall["rules"].append(f"DNS(ACCEPT)\t$FW\t${param}")
                        if (role == "ntp"):
                            shorewall["rules"].append(f"NTP(ACCEPT)\t{routable_vlan['name']}\t${param}")
                            shorewall["rules"].append(f"NTP(ACCEPT)\t$FW\t${param}")
                        if (role == "dhcp"):
                            # DHCP4 is broadcast but renew requests need to be allowd
                            shorewall["rules"].append("# DHCP broadcast handled by dhcp option in interfaces")
                            shorewall["rules"].append("# allow direct DHCP renew requests")
                            shorewall["rules"].append(f"DHCPfwd(ACCEPT)\t{routable_vlan['name']}\t${param}")
                            shorewall["rules"].append(f"DHCPfwd(ACCEPT)\t$FW\t${param}")

                if param6:
                    if not output6 and param4:
                        output6 = True
                        shorewall["params6"].append(f"{param}={param6}")
                        shorewall["rules6"].append(f"# allow access to host {host['hostname']}")

                    shorewall["rules6"].append(f"Ping(ACCEPT)\t{routable_vlan['name']}\t${param}")

                    for role in host_roles:
                        if (role == "dns"):
                            shorewall["rules6"].append(f"DNS(ACCEPT)\t{routable_vlan['name']}\t${param}")
                            shorewall["rules6"].append(f"DNS(ACCEPT)\t$FW\t${param}")
                        if (role == "ntp"):
                            shorewall["rules6"].append(f"NTP(ACCEPT)\t{routable_vlan['name']}\t${param}")
                            shorewall["rules6"].append(f"NTP(ACCEPT)\t$FW\t${param}")
                        if (role == "dhcp"):
                            shorewall["rules6"].append("# allow DHCPv6 relay")
                            shorewall["rules6"].append(f"ACCEPT\t{routable_vlan['name']}\t${param}\tudp\t546:547")
                            shorewall["rules6"].append(f"ACCEPT\t$FW\t${param}\tudp\t546:547")

        if output4:
            shorewall["rules"].append("")
        if output6:
            shorewall["rules6"].append("")


def _write_shorewall_config(cfg, shorewall, setup, output_dir):
    shorewall4 = os.path.join(output_dir, "shorewall")
    shorewall6 = os.path.join(output_dir, "shorewall6")

    os.mkdir(shorewall4)
    os.mkdir(shorewall6)

    file.write("params", "\n".join(shorewall["params"]), shorewall4)
    file.write("params", "\n".join(shorewall["params6"]), shorewall6)

    file.write("zones", "\n".join(shorewall["zones"]), shorewall4)
    file.write("zones", "\n".join(shorewall["zones6"]), shorewall6)

    file.write("interfaces", "\n".join(shorewall["interfaces"]), shorewall4)
    file.write("interfaces", "\n".join(shorewall["interfaces6"]), shorewall6)

    template = """# drop everything coming in from the internet
inet all DROP    NFLOG({0})

# reject everything else
all all REJECT  NFLOG({0})
"""
    shorewall["policy6"] = list(shorewall["policy"])
    shorewall["policy"].append(template.format(4))
    shorewall["policy6"].append(template.format(6))

    file.write("policy", "\n".join(shorewall["policy"]), shorewall4)
    file.write("policy", "\n".join(shorewall["policy6"]), shorewall6)

    file.write("snat", "\n".join(shorewall["snat"]), shorewall4)

    # TODO add ability to customize rules
    file.write("rules", "\n".join(shorewall["rules"]), shorewall4)
    file.write("rules", "\n".join(shorewall["rules6"]), shorewall6)

    shutil.copy("templates/router/ulogd.conf", output_dir)
    shutil.copy("templates/router/ulogd", output_dir)

    setup.comment("# shorewall config")
    setup.substitute("templates/router/shorewall.sh", cfg)
