"""Configuration & setup for a Kea DHCP server."""
from role.roles import Role

import util.file as file
import util.address as address

import script.shell as shell

import config.interfaces as interfaces

import config.firewall as fw


class Dhcp(Role):
    """Dhcp defines the configuration needed to setup Kea DHCP."""

    def additional_packages(self):
        return {"kea", "kea-dhcp4", "kea-dhcp6", "kea-dhcp-ddns", "kea-admin", "kea-ctrl-agent"}

    def additional_configuration(self):
        hostname = self._cfg["hostname"]

        actions4 = [fw.allow_service("dhcp", ipv6=False)]
        actions4[0]["comment"] = "allow direct DHCP renew requests"

        actions6 = [fw.allow_proto_port({"proto": "udp", "port": "546:547"}, ipv4=False)]
        actions6[0]["comment"] = "allow DHCP relay"

        # allow all routable vlans DHCP access to this host on all its interfaces
        destinations = fw.destinations_from_interfaces(self._cfg["interfaces"], hostname)

        fw.add_rule(self._cfg, [fw.location_all()], destinations, actions4,
                    f"DHCP for {hostname}; DHCP broadcast handled by dhcp option in interface config")
        fw.add_rule(self._cfg, [fw.location_all()], destinations, actions6, f"DHCP for {hostname}")

        if self._cfg["backup"]:
            self._cfg["backup_script"].comment("backup Kea leases & logs")
            self._cfg["backup_script"].append("cd /var/lib/kea; tar cfz /backup/var_lib_kea.tar.gz *")
            self._cfg["backup_script"].append("cd /var/log/kea; tar cfz /backup/var_log_kea.tar.gz *")
            self._cfg["backup_script"].blank()

    def validate(self):
        for iface in self._cfg["interfaces"]:
            if (iface["type"] == "std") and (iface["ipv4_address"] == "dhcp"):
                raise KeyError(
                    f"host '{self._cfg['hostname']}' cannot configure a DHCP server with a DHCP address on interface '{iface['name']}'")

        accessible_vlans = interfaces.check_accessiblity(self._cfg["interfaces"],
                                                         self._cfg["vswitches"].values(),
                                                         lambda vlan: not vlan["dhcp4_enabled"] and not vlan["ipv6_subnet"])

        if accessible_vlans:
            raise ValueError(f"host '{self._cfg['hostname']}' does not have access to vlans {accessible_vlans}")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0 if 'fakeisp' in site_cfg["roles_to_hostnames"] else 1

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        """Create the scripts and configuration files for the given host's configuration."""
        ifaces4 = []
        ifaces6 = []
        ifaces_by_vswitch = {}

        for iface in self._cfg["interfaces"]:
            ifaces4.append(iface["name"])
            if iface["ipv6_address"]:
                # add ipv6 address so kea will listen on it; this will allow dhcrelay to work without using ff02::1:2
                ifaces6.append(iface["name"] + "/" + str(iface["ipv6_address"]))
            ifaces_by_vswitch[iface["vswitch"]["name"]] = iface["name"]

        dhcp4_json = file.load_json("templates/kea/kea-dhcp4.conf")
        dhcp4_config = dhcp4_json["Dhcp4"]
        dhcp4_config["option-data"] = [
            {
                "name": "pcode",
                "data": "{tzposix}"  # will be replaced in setup script
            },
            {
                "name": "tcode",
                "data": "{tzname}"  # will be replaced in setup script
            }
        ]
        dhcp4_config["interfaces-config"]["interfaces"] = ifaces4

        dhcp6_json = file.load_json("templates/kea/kea-dhcp6.conf")
        dhcp6_config = dhcp6_json["Dhcp6"]
        dhcp6_config["interfaces-config"]["interfaces"] = ifaces6
        dhcp6_config["option-data"] = [
            {
                "name": "new-posix-timezone",
                "data": "{tzposix}"  # will be replaced in setup script
            },
            {
                "name": "new-tzdb-timezone",
                "data": "{tzname}"  # will be replaced in setup script
            }
        ]

        # subnets for DHCP config
        subnets_4 = []
        subnets_6 = []

        dns_server_interfaces = []
        if "dns" in self._cfg["roles_to_hostnames"]:
            # even if multiple dns servers are configured, DDNS should only update one; assume first is the primary
            dns_server_interfaces = self._cfg["hosts"][self._cfg["roles_to_hostnames"]["dns"][0]]["interfaces"]

        ntp_servers = []
        ddns_json = {}

        if "ntp" in self._cfg["roles_to_hostnames"]:
            ntp_servers = [self._cfg["hosts"][server] for server in self._cfg["roles_to_hostnames"]["ntp"]]

        if not self._cfg["domain"]:
            # no top-level domain => no vlans will have domains, so there is no need for DDNS updates
            dhcp4_config["dhcp-ddns"]["enable-updates"] = False
            dhcp6_config["dhcp-ddns"]["enable-updates"] = False

            ddns_config = {}
            ddns_dns_addresses = []
        else:
            ddns_json = file.load_json("templates/kea/kea-dhcp-ddns.conf")
            ddns_config = ddns_json["DhcpDdns"]
            # top-level domain will never have any DHCP hosts, so no need to configure DDNS forward / reverse zones

            # DNS servers for DDNS config; prefer IPv4 for updates
            dns_addresses = interfaces.find_ips_to_interfaces(self._cfg, dns_server_interfaces)
            ddns_dns_addresses = []
            for match in dns_addresses:
                if "ipv4_address" in match:
                    ddns_dns_addresses.append({"ip-address": str(match["ipv4_address"]), "port": 553})
                else:
                    ddns_dns_addresses.append({"ip-address": str(match["ipv6_address"]), "port": 553})

        ddns = False  # only use ddns if vlans have domain names defined

        # for each vlan, create a subnet configuration entry for DHCP4 & 6, along with DDNS forward and reverse zones
        for vswitch in self._cfg["vswitches"].values():
            for vlan in vswitch["vlans"]:
                # dns server addresses for this vlan
                dns_addresses = interfaces.find_ips_from_vlan(vswitch, vlan, dns_server_interfaces)
                dns4 = [str(match["ipv4_address"]) for match in dns_addresses if match["ipv4_address"]]
                dns6 = [str(match["ipv6_address"]) for match in dns_addresses if match["ipv6_address"]]
                ntp4 = []
                ntp6 = []

                if ntp_servers:
                    for server in ntp_servers:
                        ntp_addresses = interfaces.find_ips_from_vlan(vswitch, vlan, server["interfaces"])

                        for ntp in ntp_addresses:
                            if ntp["ipv4_address"]:
                                ntp4.append(str(ntp["ipv4_address"]))
                            if ntp["ipv6_address"]:
                                ntp6.append(str(ntp["ipv6_address"]))

                domains = []
                if vlan["domain"]:  # more specific domain first
                    domains.append(vlan["domain"])
                if self._cfg["domain"] and (self._cfg["domain"] != vlan["domain"]):
                    domains.append(self._cfg["domain"])

                subnet4 = {}
                subnet6 = {}

                if vlan["dhcp4_enabled"]:
                    ip4_subnet = vlan["ipv4_subnet"]

                    subnet4["subnet"] = str(ip4_subnet)
                    subnet4["pools"] = [{"pool": str(ip4_subnet.network_address + vlan["dhcp_min_address_ipv4"]) +
                                        " - " + str(ip4_subnet.network_address + vlan["dhcp_max_address_ipv4"])}]
                    if vlan["domain"]:
                        # else use top-level domain configured globally
                        subnet4["ddns-qualifying-suffix"] = vlan["domain"]

                        ddns = True
                        ddns_config["forward-ddns"]["ddns-domains"].append(
                            {"name": vlan["domain"] + ".", "dns-servers": ddns_dns_addresses})
                        ddns_config["reverse-ddns"]["ddns-domains"].append(
                            {"name": address.rptr_ipv4(ip4_subnet) + ".", "dns-servers": ddns_dns_addresses})
                    subnet4["option-data"] = [{"name": "domain-name-servers", "data":  ", ".join(dns4)},
                                              {"name": "domain-name", "data": f"{vlan['domain']}"}]
                    if domains:
                        subnet4["option-data"].append({"name": "domain-search", "data": ", ".join(domains)})
                    if vlan["routable"]:
                        subnet4["option-data"].append({"name": "routers", "data": str(ip4_subnet.network_address + 1)})
                    if ntp4:
                        subnet4["option-data"].append({"name": "ntp-servers", "data":  ", ".join(ntp4)})
                    subnet4["reservations"] = []
                    subnets_4.append(subnet4)

                if vlan["ipv6_subnet"]:
                    ip6_subnet = vlan["ipv6_subnet"]

                    subnet6["subnet"] = str(ip6_subnet)
                    subnet6["rapid-commit"] = True
                    subnet6["pools"] = []
                    if vlan["dhcp6_managed"]:
                        subnet6["pools"] = [{"pool": str(ip6_subnet.network_address + vlan["dhcp_min_address_ipv6"]) +
                                            " - " + str(ip6_subnet.network_address + vlan["dhcp_max_address_ipv6"])}]
                    # else no pool if DHCP is only informational

                    if vlan["domain"]:
                        subnet6["ddns-qualifying-suffix"] = vlan["domain"]

                        if not vlan["dhcp4_enabled"]:
                            ddns = True
                            ddns_config["forward-ddns"]["ddns-domains"].append(
                                {"name": vlan["domain"] + ".", "dns-servers": ddns_dns_addresses})
                        # forward dns already handled by ipv4
                        ddns_config["reverse-ddns"]["ddns-domains"].append(
                            {"name": address.rptr_ipv6(ip6_subnet) + ".", "dns-servers": ddns_dns_addresses})
                    subnet6["option-data"] = [{"name": "dns-servers", "data":  ", ".join(dns6)}]
                    if domains:
                        subnet6["option-data"].append({"name": "domain-search", "data": ", ".join(domains)})
                    if ntp6:
                        subnet6["option-data"].append({"name": "sntp-servers", "data":  ", ".join(ntp6)})
                    if vswitch["name"] in ifaces_by_vswitch:
                        subnet6["interface"] = ifaces_by_vswitch[vswitch["name"]]
                    subnet6["reservations"] = []
                    subnets_6.append(subnet6)

                # DHCP reservations
                for res in vlan["dhcp_reservations"]:
                    reservation = {"hostname":  res["hostname"],
                                   "hw-address": res["mac_address"].replace("-", ":").lower(), }

                    if vlan["dhcp4_enabled"]:
                        r = reservation.copy()
                        if res["ipv4_address"]:
                            r["ip-address"] = str(res["ipv4_address"])
                        subnet4["reservations"].append(r)

                    if vlan["ipv6_subnet"]:
                        r = reservation.copy()
                        if res["ipv6_address"]:
                            r["ip-addresses"] = [str(res["ipv6_address"])]  # note array for ipv6
                        subnet6["reservations"].append(r)

        if subnets_4:
            dhcp4_config["subnet4"] = subnets_4
            file.write("kea-dhcp4.conf", file.output_json(dhcp4_json), output_dir)
            setup.service("kea-dhcp4")
            setup.append("rootinstall $DIR/kea-dhcp4.conf /etc/kea")
            setup.append("tz=$(find /etc/zoneinfo | tail -n 1)")
            setup.append(
                "sed -e \"s/{tzposix}/$(tail -n1 $tz)/g\" -e \"s#{tzname}#${tz:14}#g\" -i /etc/kea/kea-dhcp4.conf")
            setup.blank()
        if subnets_6:
            dhcp6_config["subnet6"] = subnets_6
            file.write("kea-dhcp6.conf", file.output_json(dhcp6_json), output_dir)
            setup.service("kea-dhcp6")
            setup.append("rootinstall $DIR/kea-dhcp6.conf /etc/kea")
            setup.append("tz=$(find /etc/zoneinfo | tail -n 1)")
            setup.append(
                "sed -e \"s/{tzposix}/$(tail -n1 $tz)/g\" -e \"s#{tzname}#${tz:14}#g\" -i /etc/kea/kea-dhcp6.conf")
            setup.blank()
        if ddns:
            file.write("kea-dhcp-ddns.conf", file.output_json(ddns_json), output_dir)
            setup.service("kea-dhcp-ddns")
            setup.append("rootinstall $DIR/kea-dhcp-ddns.conf /etc/kea")
            setup.blank()

        if self._cfg["backup"]:
            setup.comment("restore Kea backups")
            setup.append("if [ -f $BACKUP/var_lib_kea.tar.gz ]; then")
            setup.append("  mkdir -p /var/lib/kea")
            setup.append("  cd /var/lib/kea");
            setup.append("  tar xfz /$BACKUP/var_lib_kea.tar.gz")
            setup.append("  chown -R kea:kea /var/lib/kea")
            setup.append("  chmod  750 /var/lib/kea")
            setup.append("  chmod  644 /var/lib/kea/*")
            setup.append("fi")
            setup.append("if [ -f $BACKUP/var_log_kea.tar.gz ]; then")
            setup.append("  mkdir -p /var/log/kea")
            setup.append("  cd /var/log/kea")
            setup.append("  tar xfz /$BACKUP/var_log_kea.tar.gz")
            setup.append("  chown -R kea:kea /var/log/kea")
            setup.append("  chmod  750 /var/log/kea")
            setup.append("  chmod  644 /var/log/kea/*")
            setup.append("fi")
