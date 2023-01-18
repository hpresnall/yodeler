"""Configuration & setup for a Kea DHCP server."""
import os
import os.path

import ipaddress

import util.shell
import util.file
import util.address

import config.interface as interface

from roles.role import Role


class Dhcp(Role):
    """Dhcp defines the configuration needed to setup Kea DHCP."""

    def __init__(self, cfg: dict):
        super().__init__("dhcp", cfg)

    def additional_packages(self):
        return {"kea", "kea-dhcp4", "kea-dhcp6", "kea-dhcp-ddns", "kea-admin", "kea-ctrl-agent"}

    def write_config(self, setup, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        ifaces4 = []
        ifaces6 = []
        ifaces_by_vswitch = {}

        for iface in self._cfg["interfaces"]:
            ifaces4.append(iface["name"])
            if iface["vlan"]["ipv6_subnet"]:  # ipv6 subnets are optional
                # add ipv6 address so kea will listen on it; this will allow dhcrelay to work without using ff02::1:2
                ifaces6.append(iface["name"] + "/" + str(iface["ipv6_address"]))
            ifaces_by_vswitch[iface["vswitch"]["name"]] = iface["name"]

        dhcp4_json = util.file.load_json("templates/kea/kea-dhcp4.conf")
        dhcp4_config = dhcp4_json["Dhcp4"]
        dhcp4_config["interfaces-config"]["interfaces"] = ifaces4

        dhcp6_json = util.file.load_json("templates/kea/kea-dhcp6.conf")
        dhcp6_config = dhcp6_json["Dhcp6"]
        dhcp6_config["interfaces-config"]["interfaces"] = ifaces6
        dhcp6_config["option-data"] = [
            {
                "name": "new-posix-timezone",
                "data": "{timezone}"  # will be replaced in setup script
            }
        ]

        # subnets for DHCP config
        subnets_4 = []
        subnets_6 = []

        dns_server_interfaces = self._cfg["hosts"][self._cfg["roles_to_hostnames"]["dns"][0]]["interfaces"]

        if not self._cfg["domain"]:
            # no top-level domain => no vlans will have domains, so there is no need for DDNS updates
            dhcp4_config["dhcp-ddns", "enable-updates"] = False
            dhcp6_config["dhcp-ddns", "enable-updates"] = False
        else:
            ddns_json = util.file.load_json("templates/kea/kea-dhcp-ddns.conf")
            ddns_config = ddns_json["DhcpDdns"]
            # top-level domain will never have any DHCP hosts, so no need to configure DDNS forward / reverse zones

            # DNS servers for DDNS config; prefer IPv4 for updates
            dns_addresses = interface.find_ips_to_interfaces(self._cfg, dns_server_interfaces)
            ddns_dns_addresses = []
            for match in dns_addresses:
                if "ipv4_address" in match:
                    ddns_dns_addresses.append(str(match["ipv4_address"]))
                else:
                    ddns_dns_addresses.append(str(match["ipv6_address"]))

        ddns = False  # only use ddns if vlans have domain names defined

        # for each vlan, create a subnet configuration entry for DHCP4 & 6, along with DDNS forward and reverse zones
        for vswitch in self._cfg["vswitches"].values():
            for vlan in vswitch["vlans"]:
                if not vlan["dhcp4_enabled"]:
                    continue

                # dns server addresses for this vlan
                dns_addresses = interface.find_ips_from_vlan(vswitch, vlan, dns_server_interfaces)
                dns4 = [str(match["ipv4_address"]) for match in dns_addresses if match["ipv4_address"]]
                dns6 = [str(match["ipv6_address"]) for match in dns_addresses if match["ipv6_address"]]

                domains = []
                if vlan["domain"]:  # more specific domain first
                    domains.append(vlan["domain"])
                if self._cfg["domain"]:
                    domains.append(self._cfg["domain"])

                ip4_subnet = vlan["ipv4_subnet"]

                subnet4 = {}
                subnet4["subnet"] = str(ip4_subnet)
                subnet4["pools"] = [{"pool": str(ip4_subnet.network_address + vlan["dhcp_min_address_ipv4"]) +
                                     " - " + str(ip4_subnet.network_address + vlan["dhcp_max_address_ipv4"])}]
                if vlan["domain"]:
                    subnet4["ddns-qualifying-suffix"] = vlan["domain"]  # else use top-level domain configured globally

                    ddns = True
                    ddns_config["forward-ddns"]["ddns-domains"].append(
                        {"name": vlan["domain"] + ".", "dns-servers": ddns_dns_addresses})
                    ddns_config["reverse-ddns"]["ddns-domains"].append(
                        {"name": util.address.rptr_ipv4(ip4_subnet) + ".", "dns-servers": ddns_dns_addresses})
                subnet4["option-data"] = [{"name": "dns-servers", "data":  ", ".join(dns4)}]
                if domains:
                    subnet4["option-data"].append({"name": "domain-search", "data": ", ".join(domains)})
                if vlan["routable"]:
                    subnet4["option-data"].append({"name": "routers", "data": str(ip4_subnet.network_address + 1)}),
                subnet4["reservations"] = []
                subnets_4.append(subnet4)

                if vlan["ipv6_subnet"]:  # ipv6 subnets are optional
                    ip6_subnet = vlan["ipv6_subnet"]

                    subnet6 = {}
                    subnet6["subnet"] = str(ip6_subnet)
                    subnet6["rapid-commit"] = True
                    subnet6["pools"] = []
                    if vlan["dhcp6_managed"]:  # no pool if DHCP is only informational
                        subnet6["pools"] = [{"pool": str(ip6_subnet.network_address + vlan["dhcp_min_address_ipv6"]) +
                                             " - " + str(ip6_subnet.network_address + vlan["dhcp_max_address_ipv6"])}]
                    if vlan["domain"]:
                        subnet6["ddns-qualifying-suffix"] = vlan["domain"]

                        # forward dns already handled by ipv4
                        ddns_config["reverse-ddns"]["ddns-domains"].append(
                            {"name": util.address.rptr_ipv6(ip6_subnet) + ".", "dns-servers": ddns_dns_addresses})
                    subnet6["option-data"] = [{"name": "dns-servers", "data":  ", ".join(dns6)}]
                    if domains:
                        subnet6["option-data"].append({"name": "domain-search", "data": ", ".join(domains)})
                    if vswitch["name"] in ifaces_by_vswitch:
                        subnet6["interface"] = ifaces_by_vswitch[vswitch["name"]]
                    subnet6["reservations"] = []
                    subnets_6.append(subnet6)

                # DHCP reservations
                for res in vlan["dhcp_reservations"]:
                    reservation = {"hostname":  res["hostname"],
                                   "hw-address": res["mac_address"].replace("-", ":").lower(), }

                    r = reservation.copy()
                    if res["ipv4_address"]:
                        r["ip-address"] = str(res["ipv4_address"])
                    subnet4["reservations"].append(r)

                    r = reservation.copy()
                    if res["ipv6_address"]:
                        r["ip-addresses"] = [str(res["ipv6_address"])]  # note array for ipv6
                    subnet6["reservations"].append(r)

        dhcp4_config["subnet4"] = subnets_4
        dhcp6_config["subnet6"] = subnets_6

        util.file.write("kea-dhcp4.conf", util.file.output_json(dhcp4_json), output_dir)
        util.file.write("kea-dhcp6.conf", util.file.output_json(dhcp6_json), output_dir)
        if ddns:
            util.file.write("kea-dhcp-ddns.conf", util.file.output_json(ddns_json), output_dir)

        setup.service("kea-dhcp4")
        setup.service("kea-dhcp6")
        if ddns:
            setup.service("kea-dhcp-ddns")
        setup.blank()
        setup.append("rootinstall $DIR/kea-dhcp4.conf /etc/kea")
        setup.append("rootinstall $DIR/kea-dhcp6.conf /etc/kea")
        if ddns:
            setup.append("rootinstall $DIR/kea-dhcp-ddns.conf /etc/kea")
        setup.blank()
        setup.append("sed -e \"s/{timezone}/$(tail -n1 /etc/localtime)/g\"  -i /etc/kea/kea-dhcp6.conf")
