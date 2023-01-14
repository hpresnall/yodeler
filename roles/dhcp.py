"""Configuration & setup for a Kea DHCP server."""
import os
import os.path

import ipaddress

import util.shell
import util.file
import util.address

import config.interface

from roles.role import Role


class Dhcp(Role):
    """Dhcp defines the configuration needed to setup Kea DHCP."""

    def __init__(self):
        super().__init__("dhcp")

    def additional_packages(self, cfg):
        return {"kea", "kea-dhcp4", "kea-dhcp6", "kea-dhcp-ddns", "kea-admin", "kea-ctrl-agent"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        dns4 = []
        dns6 = []
        ddns = False
        if cfg["roles_to_hostnames"]["dns"]:
            dns_addresses = config.interface.find_ip_addresses(
                cfg, cfg["hosts"][cfg["roles_to_hostnames"]["dns"][0]]["interfaces"])

            dns4 = [str(match["ipv4_address"]) for match in dns_addresses if match["ipv4_address"]]
            dns6 = [str(match["ipv6_address"]) for match in dns_addresses if match["ipv6_address"]]

            ddns = (len(dns4) > 0) or (len(dns6) > 0)
        else:
            dns4 = cfg["external_dns"] # TODO split external into 4 and 6

        ifaces4 = []
        ifaces6 = []
        ifaces_by_vswitch = {}

        for iface in cfg["interfaces"]:
            ifaces4.append(iface["name"])
            if iface["vlan"]["ipv6_subnet"]:  # ipv6 subnets are optional
                # add ipv6 address so kea will listen on it; this will allow dhcrelay to work without using ff02::1:2
                ifaces6.append(iface["name"] + "/" + str(iface["ipv6_address"]))
            ifaces_by_vswitch[iface["vswitch"]["name"]] = iface["name"]

        dhcp4_json = util.file.load_json("templates/kea/kea-dhcp4.conf")
        dhcp4_config = dhcp4_json["Dhcp4"]
        dhcp4_config["interfaces-config"]["interfaces"] = ifaces4
        dhcp4_config["option-data"] = [
            {
                "name": "domain-name-servers",
                "data":  ", ".join(dns4)
            }
        ]

        dhcp6_json = util.file.load_json("templates/kea/kea-dhcp6.conf")
        dhcp6_config = dhcp6_json["Dhcp6"]
        dhcp6_config["interfaces-config"]["interfaces"] = ifaces6
        dhcp6_config["option-data"] = [
            {
                "name": "dns-servers",
                "data":  ", ".join(dns6)
            },
            {
                "name": "new-posix-timezone",
                "data": "{timezone}"  # will be replaced in setup script
            }
        ]

        if not cfg["domain"]:
            # no top-level domain => no vlans will have domains, so there is no need for DDNS updates
            dhcp4_config["dhcp-ddns", "enable-updates"] = False
            dhcp6_config["dhcp-ddns", "enable-updates"] = False
        # else top-level domain will never have any DHCP hosts, so no need to configure DDNS forward / reverse zones

        # subnets for DHCP config
        subnets_4 = []
        subnets_6 = []

        # DNS servers for DDNS config; will use IPv4 only for updates
        # TODO use localhost if DHCP and DNS are the same host
        dns_servers4 = []
        for dns in dns4:
            dns_servers4.append({"ip-address": dns})

        ddns_json = util.file.load_json("templates/kea/kea-dhcp-ddns.conf")
        ddns_config = ddns_json["DhcpDdns"]

        # for each vlan, create a subnet configuration entry for DHCP4 & 6, along with DDNS forward and reverse zones
        for vswitch in cfg["vswitches"].values():
            for vlan in vswitch["vlans"]:
                if not vlan["dhcp_enabled"]:
                    continue

                domains = []
                if vlan["domain"]:  # more specific domain first
                    domains.append(vlan["domain"])
                if cfg["domain"]:
                    domains.append(cfg["domain"])

                ip4_subnet = vlan["ipv4_subnet"]

                subnet4 = {}
                subnet4["subnet"] = str(ip4_subnet)
                subnet4["pools"] = [{"pool": str(ip4_subnet.network_address + vlan["dhcp_min_address_ipv4"]) +
                                     " - " + str(ip4_subnet.network_address + vlan["dhcp_max_address_ipv4"])}]
                if vlan["domain"]:
                    subnet4["ddns-qualifying-suffix"] = vlan["domain"]  # else use top-level domain configured globally

                    ddns_config["forward-ddns"]["ddns-domains"].append(
                        {"name": vlan["domain"] + ".", "dns-servers": dns_servers4})
                    ddns_config["reverse-ddns"]["ddns-domains"].append(
                        {"name": util.address.rptr_ipv4(ip4_subnet) + ".", "dns-servers": dns_servers4})
                subnet4["option-data"] = [{"name": "routers", "data": str(ip4_subnet.network_address + 1)}]
                if domains:
                    subnet4["option-data"].append({"name": "domain-search", "data": ", ".join(domains)})
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
                            {"name": util.address.rptr_ipv6(ip6_subnet) + ".", "dns-servers": dns_servers4})
                    if domains:
                        subnet6["option-data"] = [{"name": "domain-search", "data": ", ".join(domains)}]
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

        kea = util.shell.ShellScript("kea.sh")

        kea.append("rc-update add kea-dhcp4 default")
        kea.append("rc-update add kea-dhcp6 default")
        if ddns:
            kea.append("rc-update add kea-dhcp-ddns default")
        kea.append("")
        kea.append("rootinstall $DIR/kea-dhcp4.conf /etc/kea")
        kea.append("rootinstall $DIR/kea-dhcp6.conf /etc/kea")
        if ddns:
            kea.append("rootinstall $DIR/kea-dhcp-ddns.conf /etc/kea")
        kea.append("")
        kea.append("sed -e \"s/{timezone}/$(tail -n1 /etc/localtime)/g\"  -i /etc/kea/kea-dhcp6.conf")
        kea.append("")

        kea.write_file(output_dir)

        return [kea.name]
