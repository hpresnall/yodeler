"""Configuration & setup for a Shorewall based router."""
import os.path
import os

from role.roles import Role

import util.file as file
import util.parse as parse

import script.libvirt as libvirt
import script.shell as shell
import script.sysctl as sysctl

import config.interfaces as interfaces
import config.firewall as fw


class Router(Role):
    """Router defines the configuration needed to setup a system that can route from the configured
     vlans to the internet"""

    def additional_packages(self):
        return {"shorewall", "shorewall6", "ipset", "radvd", "ulogd", "ulogd-json", "dhcrelay", "ndisc6", "tcpdump", "ethtool"}

    def additional_aliases(self) -> list[str]:
        return ["gateway", "firewall"]

    def configure_interfaces(self):
        uplink = interfaces.configure_uplink(self._cfg)

        # add an interface for each vswitch that has routable vlans
        vswitch_interfaces = []

        for vswitch in self._cfg["vswitches"].values():
            mac_address = None

            if self._cfg["is_vm"]:
                # create an interface for each vswitch
                # note that it will only be used if the vswitch has routable vlans
                # routers must explicitly add interfaces for non-routable vlans
                iface_name = vswitch["name"]
                mac_address = interfaces.random_mac_address()
            elif vswitch["uplinks"]:
                # TODO handle multiple uplinks; maybe just error instead of creating physical bond ifaces
                # TODO if site also has a separate, physical vmhost, then need a way to
                # differentiate uplinks for vmhost vs router; maybe router_iface in vswitch config?
                iface_name = vswitch["uplinks"][0]

                # vswitch validation already confirmed uplink uniqueness among all vswitches
                if iface_name == uplink["name"]:
                    raise ValueError("router uplink cannot use the same interface as vswitch"
                                     f"{vswitch['name']}: {iface_name}")
            else:
                # physical server with no uplink; will error if this vswitch has routable vlans
                iface_name = "missing"

            vlan_interfaces = []
            untagged = False
            untagged_iface = None

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                vlan_iface = interfaces.for_vlan(iface_name, vswitch, vlan, mac_address)
                vlan["router_iface"] = vlan_iface
                vlan_interfaces.append(vlan_iface)

                if vlan["id"] is None:
                    untagged = True
                    untagged_iface = vlan_iface

                # will add a prefix delegation stanza to dhcpcd.conf for the vlan; see dhcpcd.py
                pd_network = vlan["ipv6_pd_network"]
                _validate_vlan_pd_network(uplink["ipv6_pd_prefixlen"], pd_network)
                uplink["ipv6_delegated_prefixes"].append(f"{vlan_iface['name']}/{pd_network}")

            if vlan_interfaces:  # i.e. any routable vlans
                if iface_name == "missing":
                    raise ValueError(f"vswitch {vswitch['name']} has routable vlans, but does not define an uplink")

                # create the parent interface for the vlan interfaces
                comment = f"vlans on '{vswitch['name']}' vswitch"

                if untagged:  # interface with no vlan tag already created; add the comment on the first interface
                    vlan_interfaces[0]["comment"] = comment
                    vswitch["router_iface"] = untagged_iface
                else:  # add the base interface as a port
                    # append to vswitch_interfaces to ensure it is defined before the sub-interfaces for the vlans
                    iface = interfaces.for_port(iface_name, comment, "vlan", mac_address=mac_address)
                    vswitch["router_iface"] = iface
                    vswitch_interfaces.append(iface)

                vswitch_interfaces.extend(vlan_interfaces)
        # end for all vswitches

        # set uplink after vswitch interfaces in /etc/interfaces so all the vlans are up before prefix delgation
        ifaces = self._cfg.setdefault("interfaces", [])

        # rename all the interfaces that have a mac address, i.e. this is a vm and these are virtual interfaces
        # non-vm routers should set rename rules in the yaml config
        # TODO add optional 'downlink' configuration to allow physical servers to set an interface & mac_address; require vswitch name if more than one
        for iface in vswitch_interfaces:
            if iface["mac_address"]:
                self._cfg["rename_interfaces"].append({"name": iface["name"], "mac_address": iface["mac_address"]})

        if not isinstance(ifaces, list):
            raise KeyError(f"cfg['interfaces'] must be a list")

        self._cfg["interfaces"] = vswitch_interfaces + [uplink] + ifaces

    def additional_configuration(self):
        # router will use Shorewall instead
        self._cfg["local_firewall"] = False

        hostname = self._cfg["hostname"]

        # allow pings to and from the firewall
        ping = fw.allow_service("ping")

        fw.add_rule(self._cfg, [fw.location_firewall()], [fw.location_all(), fw.location_internet()],
                    [ping], f"firewall ({hostname}) can ping everything")
        fw.add_rule(self._cfg, [fw.location_all()], [fw.location_firewall()],
                    [ping], f"allow pings to the firewall ({hostname})")

        # allow other services
        fw.add_rule(self._cfg, [fw.location_firewall()], [fw.location_internet()],
                    [fw.allow_service("traceroute")], f"allow traceroute from the firewall ({hostname})")
        fw.add_rule(self._cfg, [fw.location_firewall()], [fw.location_internet()],
                    [fw.allow_service("dns")],
                    f"firewall ({hostname}) can send DNS out so it does not depend on local DNS being up")

        if self._cfg["backup"]:
            self._cfg["backup_script"].comment("backup firewall logs")
            self._cfg["backup_script"].append("mkdir -p /backup/firewall; cp /var/log/firewall/* /backup/firewall")
            self._cfg["backup_script"].blank()

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

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        """Create the scripts and configuration files for the given host's configuration."""
        uplink = parse.non_empty_dict("router 'uplink'", self._cfg.get("uplink"))

        libvirt_interfaces = []

        if self._cfg["is_vm"]:
            # create libvirt uplink interface
            if "macvtap" in uplink:
                uplink_xml = libvirt.macvtap_interface(uplink)
            elif "passthrough" in uplink:
                uplink_xml = libvirt.passthrough_interface(uplink["passthrough"], uplink["mac_address"])
            else:  # use vswitch+vlan
                uplink_xml = libvirt.interface_from_config(self._cfg["hostname"], uplink)

            # add an interface to the host's libvirt definition for each vswitch; order matches network_interfaces
            libvirt_interfaces = [uplink_xml]

        shorewall = _init_shorewall(self._cfg)

        radvd_template = file.read_template(self.name, "radvd.conf")
        radvd_config = []

        dhrelay4_ifaces = []
        dhrelay6_ifaces = []

        for vswitch in self._cfg["vswitches"].values():
            has_routable_vlans = False
            comment = False

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                has_routable_vlans = True

                _configure_shorewall_vlan(shorewall, vswitch["name"], vlan)

                if vlan["dhcp4_enabled"]:
                    dhrelay4_ifaces.append(vlan["router_iface"]["name"])

                if not vlan["ipv6_disabled"]:
                    # find all accessible DNS addresses for this vlan and add them to the RDNSS entry for radvd
                    dns_addresses = []
                    for dns_hostname in self._cfg["roles_to_hostnames"]["dns"]:
                        for match in interfaces.find_ips_from_vlan(vswitch, vlan, self._cfg["hosts"][dns_hostname]["interfaces"]):
                            if match["ipv6_address"]:
                                dns_addresses.append(str(match["ipv6_address"]))
                    rdnss = "RDNSS " + " ".join(dns_addresses) + \
                        " {};" if dns_addresses else "# no DNS servers => no RDNSS entries"

                    # add the vlan and top level site domain to the DNSSL entry for radvd
                    domain = vlan["domain"] if vlan["domain"] else ""
                    domain += " " + self._cfg["domain"] if self._cfg["domain"] else ""
                    dnssl = "DNSSL " + domain + " {};" if domain else "# no domains set => no DNSSL entries"

                    radvd_config.append(radvd_template.format(
                        vlan["router_iface"]["name"],
                        "on" if vlan["dhcp6_managed"] else "off",  # dhcp6_managed == True => AdvManagedFlag on
                        rdnss,
                        dnssl
                    ))

                    dhrelay6_ifaces.append(vlan["router_iface"])
            # for each vlan

            if has_routable_vlans:
                if not comment:
                    shorewall["params"].append("\n# parent interface for vswitch " + vswitch["name"])
                    shorewall["params6"].append("\n# parent interface for vswitch " + vswitch["name"])
                    comment = True
                # shorewall param to associate vswitch with interface
                param = vswitch["name"].upper() + "=" + vswitch["router_iface"]["name"]
                shorewall["params"].append(param)
                shorewall["params6"].append(param)

                if self._cfg["is_vm"]:
                    # new libvirt interface to trunk the vlans
                    libvirt_interfaces.append(libvirt.router_interface(
                        self._cfg['hostname'], vswitch, vswitch["router_iface"]["mac_address"]))
        # for each vswitch

        _add_shorewall_host_params(self._cfg, shorewall)

        for idx, rule in enumerate(self._cfg["firewall"]["rules"], start=1):
            _create_shorewall_rule(rule, idx, shorewall)

        _write_shorewall_config(self._cfg, shorewall, setup, output_dir)

        setup.service("shorewall", "boot")
        if radvd_config:  # ipv6 enabled on at least one vlan
            setup.service("shorewall6", "boot")
        setup.blank()

        _write_ipsets(self._cfg, setup)
        _write_dhcrelay_config(self._cfg, setup, dhrelay4_ifaces, dhrelay6_ifaces, shorewall)

        file.copy_template("router", "ulogd.conf", output_dir)
        file.copy_template("router", "logrotate-firewall", output_dir)

        if self._cfg["is_vm"]:
            libvirt.update_interfaces(self._cfg['hostname'], libvirt_interfaces, output_dir)

        if radvd_config:
            file.write("radvd.conf", "\n".join(radvd_config), output_dir)

            setup.append("rootinstall radvd.conf /etc")
            setup.service("radvd", "boot")

        if dhrelay6_ifaces:  # at least one interface needs dhcp6
            sysctl.enable_ipv6_forwarding(setup, output_dir)

        # add sysctl params for performance
        setup.append("echo \"net.ipv6.route.max_size = 16384\" >> /etc/sysctl.conf")

        if self._cfg["backup"]:
            setup.blank()
            setup.comment("restore firewall log backups")
            setup.append("if [ -f $BACKUP/firewall ]; then")
            setup.append("  mkdir -p /var/log/firewall")
            setup.append("  cp $BACKUP/firewall/* /var/log/firewall")
            setup.append("  chown root:wheel /var/log/firewall")
            setup.append(  "chmod 750 /var/log/firewall")
            setup.append("  chown -R root:root /var/log/firewall/*")
            setup.append("  chmod 640 /var/log/firewall/*")
            setup.append("fi")


def _validate_vlan_pd_network(prefixlen: int, ipv6_pd_network: int):
    if ipv6_pd_network is not None:
        maxnetworks = 2 ** (64 - prefixlen)
        if ipv6_pd_network >= maxnetworks:
            raise KeyError((f"pd network {ipv6_pd_network} is larger than the {maxnetworks} " +
                            f" networks available with the 'ipv6_pd_prefixlen' of {prefixlen}"))


def _write_dhcrelay_config(cfg: dict, setup: shell.ShellScript, dhrelay4_ifaces: list, dhrelay6_ifaces: list, shorewall: dict):
    dhcp_server = cfg["hosts"][cfg["roles_to_hostnames"]["dhcp"][0]]
    dhcp_addresses = interfaces.find_ips_to_interfaces(cfg, dhcp_server["interfaces"], first_match_only=False)

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

        setup.append(file.read_template("router", "dhcrelay6.sh"))

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
        # set explicit address on the upper iface to avoid another multicast request
        upper_iface6_name = dhcp_addresses["src_iface"]["name"]
        upper_iface6 = str(dhcp_addresses["ipv6_address"]) + "%" + upper_iface6_name

        # set explicit addreses on the lower interfaces so the dhcp server is receving a relay from a known, static network
        # also remove upper iface from list; no need to relay traffic in the same subnet
        dhrelay6_ifaces = [str(iface["ipv6_address"]) + "%" + iface["name"]
                           for iface in dhrelay6_ifaces if iface["name"] != upper_iface6_name]

        setup.comment("setup dhcrelay6.conf")
        setup.append("echo 'IFACE=\"" + " ".join(dhrelay6_ifaces) + "\"' >> /etc/conf.d/dhcrelay6")
        setup.append(f"echo 'DHCRELAY_SERVERS=\"-u {upper_iface6}\"' >> /etc/conf.d/dhcrelay6")
        setup.service("dhcrelay6")
        setup.blank()


def _init_shorewall(cfg: dict):
    # dict of shorewall config files; will be appended for each vswitch / vlan
    shorewall = {}
    shorewall["params"] = ["# router uplink\nINTERNET=" + cfg["uplink"]["name"]]
    shorewall["params6"] = ["# router uplink\nINTERNET=" + cfg["uplink"]["name"]]
    shorewall["zones"] = ["fw\tfirewall\ninet\tipv4"]
    shorewall["zones6"] = ["fw\tfirewall\ninet\tipv6"]
    shorewall["interfaces"] = ["inet\t$INTERNET\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"]
    # accept_ra=0 => let dhcpcd manage router advertizements
    shorewall["interfaces6"] = ["inet\t$INTERNET\ttcpflags,dhcp,rpfilter,accept_ra=0"]
    shorewall["policy"] = []
    shorewall["snat"] = []
    shorewall["rules"] = [file.read_template("router/shorewall", "rules")]
    shorewall["rules6"] = [file.read_template("router/shorewall", "rules6")]

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
    # disable router advertisements on downstream interfaces
    # dhcpcd will assign addresses, no need for SLAAC
    shorewall["interfaces6"].append((f"{vlan_name}\t{shorewall_name}\ttcpflags,dhcp,rpfilter,accept_ra=0"))

    # snat only on ipv4; ipv6 will be routable
    shorewall["snat"].append(f"MASQUERADE\t{vlan['ipv4_subnet']}\t$INTERNET")


def _add_shorewall_host_params(cfg: dict, shorewall: dict):
    # add a param for each host interface if it is on a routable vlan and has an address
    shorewall["params"].append("\n# Yodeler defined hosts")
    shorewall["params6"].append("\n# Yodeler defined hosts")

    for host in cfg["hosts"].values():
        for iface in host["interfaces"]:
            if (iface["type"] not in {"std", "vlan"}) or (not iface["vlan"]["routable"]):
                continue

            if iface["vlan"]["routable"]:
                vlan_name = iface["vlan"]["name"]
                host_vlan = (host["hostname"] + "_" + vlan_name).upper()

                if iface["ipv4_address"] != "dhcp":
                    shorewall["params"].append(f"{host_vlan}={vlan_name}:{iface['ipv4_address']}")
                if iface["ipv6_address"]:
                    shorewall["params6"].append(f"{host_vlan}={vlan_name}:{iface['ipv6_address']}")

    # for vlan DHCP reservations & static hosts, add a param if an ip address exists
    # firewall config will not allow rules if there is no address and ensures aliases are not used
    comment4 = comment6 = False

    for vswitch in cfg["vswitches"].values():
        for vlan in vswitch["vlans"]:
            if not vlan["routable"]:
                continue  # no need to add non-routable reservations to the firewall

            vlan_name = vlan['name']

            for host in vlan["dhcp_reservations"] + vlan["static_hosts"]:
                if host["ipv4_address"]:
                    if not comment4:
                        shorewall["params"].append("\n# ip addresses from DHCP reservations & static hostnames")
                        comment4 = True
                    shorewall["params"].append(
                        f"{host['hostname'].upper()}_{vlan_name.upper()}={vlan_name}:{host['ipv4_address']}")
                if host["ipv6_address"]:
                    if not comment6:
                        shorewall["params6"].append("\n# ip addresses from DHCP reservations & static hostnames")
                        comment6 = True
                    shorewall["params6"].append(
                        f"{host['hostname'].upper()}_{vlan_name.upper()}={vlan_name}:{host['ipv6_address']}")

    comment4 = comment6 = False

    for host in cfg["external_hosts"]:
        if host["ipv4_address"]:
            if not comment4:
                shorewall["params"].append("\n# ip addresses from external hosts")
                comment4 = True
            for hostname in host["hostnames"]:
                hostname = hostname.upper().replace(".", "_")
                shorewall["params"].append(
                    f"{hostname}_INET=inet:{host['ipv4_address']}")
        if host["ipv6_address"]:
            if not comment6:
                shorewall["params6"].append("\n# ip addresses from external_hosts")
                comment6 = True
            for hostname in host["hostnames"]:
                hostname = hostname.upper().replace(".", "_")
                shorewall["params6"].append(
                    f"{hostname}_INET=inet:{host['ipv6_address']}")


# map firewall keywords to shorwall macro names
_allowed_macros = {
    "ping": "Ping",
    "traceroute": "Trcrt",
    "ssh": "SSH",
    "telnet": "Telnet",
    "dns": "DNS",
    "dhcp": "DHCPfwd",
    "ntp": "NTP",
    "smb": "SMB",
    "samba": "SMB",
    "web": "Web",
    "ftp": "FTP",
    "mail": "Mail",
    "pop3": "POP3",
    "imap": "IMAP",
    "imaps": "IMAPS"
}

for service in fw.named_services:
    if service not in _allowed_macros:
        raise KeyError(f"firewall service '{service}' has no Shorewall macro defined")


def _build_shorewall_location(location: dict) -> str:
    vlan = location["vlan"]

    if vlan["name"] == "internet":
        vlan = "inet"  # param name used in Shorewall interfaces file
    elif vlan["name"] == "all":
        # host, ipset and ip address are ignored
        return "all"
    elif vlan["name"] == "firewall":
        # Shorewall firewall zone name
        # host, ipset and ip address are not allowed for firewall vlan
        return "$FW"
    else:
        vlan = vlan["name"]  # also handles 'all'

    # location from firewall.py has optional hostname, ipset or ip address
    if "hostname" in location:
        # set to value used in Shorewall params
        if vlan == "inet":
            return f"${location['hostname'].upper().replace(".", "_")}_{vlan.upper()}"
        else:
            return f"${location['hostname'].upper()}_{vlan.upper()}"
    elif "ipset" in location:
        return f"{vlan}:+{location['ipset']}"
    else:
        return vlan


def _add_ipadress_to_shorewall_location(location: dict, shorewall_loc: str, ip_version: int) -> str:
    key = f"ip{ip_version}_version"

    if key in location:
        address = location["key"]
        # assume firewall config already confirmed address matches ip version
        return f"{shorewall_loc}:{address}"

    return shorewall_loc


def _create_shorewall_rule(rule: dict, rule_idx: int, shorewall: dict):
    loc = f"firewall.rules[{rule_idx}]"
    actions4 = []
    actions6 = []
    allow_all_comment = True

    # for every source/destination combo
    for source in rule["sources"]:
        s = _build_shorewall_location(source)
        s4 = _add_ipadress_to_shorewall_location(source, s, 4)
        s6 = _add_ipadress_to_shorewall_location(source, s, 6)

        for destination in rule["destinations"]:
            d = _build_shorewall_location(destination)
            d4 = _add_ipadress_to_shorewall_location(destination, d, 4)
            d6 = _add_ipadress_to_shorewall_location(destination, d, 6)

            for action in rule["actions"]:
                a = action["action"]

                if (a == "allow") or (a == "allow-all"):
                    a = "ACCEPT"
                elif a == "forward":
                    a = "DNAT"
                else:
                    a = a.upper()

                # only output rules if ip version is supported
                ipv4 = source["ipv4"] and destination["ipv4"] and action["ipv4"]
                ipv6 = source["ipv6"] and destination["ipv6"] and action["ipv6"]

                if action["type"] == "allow-all":
                    # append rule directly to policy file, commenting only once
                    # policy for ipv6 is copied; avoid duplicate output
                    if allow_all_comment and rule["comment"]:
                        shorewall["policy"].append("# " + rule["comment"])
                        allow_all_comment = False
                    shorewall["policy"].append(s + '\t' + d + '\t' + a + '\n')
                elif action["type"] == "named":
                    if action["protocol"] in _allowed_macros:
                        a = _allowed_macros[action["protocol"]] + '(' + a + ')'
                    else:
                        raise ValueError(
                            f"invalid firewall rule {rule_idx}; {action['protocol']} is not a valid protocol")

                    comment = ""
                    if action["comment"]:
                        comment = "\t# " + action["comment"]

                    if ipv4:
                        actions4.append(a + '\t' + s4 + '\t' + d4 + comment)
                    if ipv6:
                        actions6.append(a + '\t' + s6 + '\t' + d6 + comment)
                elif action["type"] == "protoport":
                    protocol = action["protocol"]
                    n = len(action["ports"])

                    # add comment at the end of the line if there is only one line of output
                    if n > 1 and action["comment"]:
                        if ipv4:
                            actions4.append("# " + action["comment"])
                        if ipv4:
                            actions6.append("# " + action["comment"])

                    for i, port in enumerate(action["ports"]):
                        if (i == 0) and (n == 1) and action["comment"]:
                            comment = "\t# " + action["comment"]
                        else:
                            comment = ""

                        if ipv4:
                            actions4.append(a + '\t' + s4 + '\t' + d4 + '\t' + protocol + '\t' + port + comment)
                        if ipv6:
                            actions6.append(a + '\t' + s6 + '\t' + d6 + '\t' + protocol + '\t' + port + comment)
                else:
                    raise ValueError(f"{loc} invalid firewall rule {rule_idx}; unknown action type '{action['type']}'")

    if len(actions4) > 0:
        if rule["comment"]:
            shorewall["rules"].append("# " + rule["comment"])
        shorewall["rules"].extend(actions4)
        shorewall["rules"].append("")

    if len(actions6) > 0:
        if rule["comment"]:
            shorewall["rules6"].append("# " + rule["comment"])
        shorewall["rules6"].extend(actions6)
        shorewall["rules6"].append("")


def _write_shorewall_config(cfg: dict, shorewall: dict, setup: shell.ShellScript, output_dir: str):
    shorewall4 = os.path.join(output_dir, "shorewall")
    shorewall6 = os.path.join(output_dir, "shorewall6")

    os.mkdir(shorewall4)
    os.mkdir(shorewall6)

    # end with blank line for all generated files; policy templates already include
    for key in ["params", "params6", "zones", "zones6", "interfaces", "interfaces6", "rules", "rules6", "snat"]:
        shorewall[key].append("")

    file.write("params", "\n".join(shorewall["params"]), shorewall4)
    file.write("params", "\n".join(shorewall["params6"]), shorewall6)

    file.write("zones", "\n".join(shorewall["zones"]), shorewall4)
    file.write("zones", "\n".join(shorewall["zones6"]), shorewall6)

    file.write("interfaces", "\n".join(shorewall["interfaces"]), shorewall4)
    file.write("interfaces", "\n".join(shorewall["interfaces6"]), shorewall6)

    # virtio devices do not calculate the correct udp checksums; add rules compute them manually
    if cfg["is_vm"]:
        # POSTROUTING on source port 53 for dns responses
        dns = "CHECKSUM:T\t-\t-\tudp\t-\t53\n"
        # POSTROUTING on destination port 546 for dhcrelay6 responses to clients
        dhcrelay6 = "CHECKSUM:T\t-\t-\tudp\t546\n"

        file.write("mangle", dns, shorewall4)
        file.write("mangle", dns + dhcrelay6, shorewall6)

    template = """# drop everything coming in from the internet
inet\tall\tDROP\tNFLOG({0})

# reject everything else
all\tall\tREJECT\tNFLOG({0})
"""
    shorewall["policy6"] = list(shorewall["policy"])
    shorewall["policy"].append(template.format(4))
    shorewall["policy6"].append(template.format(6))

    file.write("policy", "\n".join(shorewall["policy"]), shorewall4)
    file.write("policy", "\n".join(shorewall["policy6"]), shorewall6)

    file.write("snat", "\n".join(shorewall["snat"]), shorewall4)

    file.write("rules", "\n".join(shorewall["rules"]), shorewall4)
    file.write("rules", "\n".join(shorewall["rules6"]), shorewall6)

    setup.comment("# shorewall config")
    setup.substitute("router", "shorewall.sh", cfg)


def _write_ipsets(cfg: dict, setup: shell.ShellScript):
    setup.append(file.read_template("router", "ipsets.sh"))

    for name, ipset in cfg["firewall"]["ipsets4"].items():
        setup.append(
            f"echo \"create {name} hash:{ipset['type']} family {ipset['family']} hashsize {ipset['hashsize']} maxelem {len(ipset['addresses'])}\" >> $IPSETS_4")

        for address in ipset["addresses"]:
            setup.append(f"echo \"add {name} {address}\" >> $IPSETS_4")

        setup.blank()

    for name, ipset in cfg["firewall"]["ipsets6"].items():
        setup.append(
            f"echo \"create {name} hash:{ipset['type']} family {ipset['family']} hashsize {ipset['hashsize']} maxelem {len(ipset['addresses'])}\" >> $IPSETS_6")

        for address in ipset["addresses"]:
            setup.append(f"echo \"add {name} {address}\" >> $IPSETS_6")

        setup.blank()

    setup.append("ipset restore < $IPSETS_4")
    setup.append("ipset restore < $IPSETS_6")
