import util.shell

import ipaddress

from roles.role import Role

import config.vlan
import config.interface

import util.file


class FakeISP(Role):
    def additional_packages(self) -> set[str]:
        return {"kea", "kea-dhcp4", "kea-dhcp6", "kea-admin", "kea-ctrl-agent", "iptables"}

    def configure_interfaces(self):
        # ensure required vswitches and vlans exist
        if "fakeinternet" not in self._cfg["vswitches"]:
            raise ValueError(f"site '{self._cfg['site']}' does not define a 'fakeinternet' vswitch")
        if "fakeisp" not in self._cfg["vswitches"]:
            raise ValueError(f"site '{self._cfg['site']}' does not define a 'fakeisp' vswitch")

        # note vlan=fakeinet but vswitch=fakeinternet
        finet_vlan = config.vlan.lookup("fakeinet", self._cfg["vswitches"]["fakeinternet"])
        fisp_vlan = config.vlan.lookup("fakeisp", self._cfg["vswitches"]["fakeisp"])

        # define interfaces for both vswitches, if not already configured
        interfaces = self._cfg.pop("interfaces", [])
        fakeinternet: dict = {}
        fakeisp: dict = {}

        for iface in interfaces:
            vswitch = iface.get("vswitch")

            if vswitch == "fakeinternet":
                fakeinternet = iface
            if vswitch == "fakeisp":
                fakeisp = iface

        if not fakeinternet:
            fakeinternet = {
                "vswitch": "fakeinternet"
            }
        fakeinternet["forward"] = True  # required to forward from fakeisp network
        fakeinternet.setdefault("ipv4_address", "dhcp")

        if not fakeisp:
            fakeisp = {
                "vswitch": "fakeisp"
            }

        fakeisp.setdefault("ipv4_address", str(fisp_vlan["ipv4_subnet"].network_address + 1))
        if fisp_vlan.get("ipv6_subnet"):
            fakeisp.setdefault("ipv6_address",  str(fisp_vlan["ipv6_subnet"].network_address + 1))
            # disable passing through existing ipv6 config
            fakeisp["accept_ra"] = False
            fakeisp["ipv6_dhcp"] = False

        # order so fakeinternet, then fakeisp with parent interfaces first
        # note, this silently ignores interfaces on other vswitches
        self._cfg["interfaces"] = [fakeinternet, fakeisp]

        # create the parent interface for tagged vlans
        # vmhosts will configure the vswitches to vlan tag, so parents are not necessary
        if ("vmhost") in self._cfg["roles_to_hostnames"] and (self._cfg["hostname"] not in self._cfg["roles_to_hostnames"]["vmhost"]):
            if (fisp_vlan["id"] is not None):
                parent = fakeisp.get("name", "eth1")
                self._cfg["interfaces"].insert(1, config.interface.for_port(parent, "vlans on 'fakeisp' vswitch"))

            if (finet_vlan["id"] is not None):
                parent = fakeinternet.get("name", "eth0")
                self._cfg["interfaces"].insert(0, config.interface.for_port(parent, "vlans on 'fakeiternet' vswitch"))

    def additional_configuration(self):
        # configure iptables manually; no need for awall
        self._cfg["local_firewall"] = False

        self.add_alias("fakeisp")

    def validate(self):
        pass

    def write_config(self, setup: util.shell.ShellScript, output_dir: str):
        fakeinternet = fakeisp = vlan = {}

        for iface in self._cfg["interfaces"]:
            if iface["type"] != "std":
                continue
            if iface["vlan"]["name"] == "fakeinet":
                fakeinternet = iface
            if iface["vlan"]["name"] == "fakeisp":
                fakeisp = iface
                vlan = iface["vlan"]

        iptables = {
            "FAKEINTERNET_IFACE": fakeinternet["name"],
            "FAKEISP_IFACE": fakeisp["name"]
        }
        setup.substitute("templates/fakeisp/iptables.sh", iptables)
        setup.service("iptables", "boot")
        setup.blank()
        setup.substitute("templates/fakeisp/ip6tables.sh", iptables)
        setup.service("ip6tables", "boot")
        setup.blank()

        external_dns = [ipaddress.ip_address(ip) for ip in self._cfg["external_dns"]]

        subnet = vlan["ipv4_subnet"]
        dns = [str(ip) for ip in external_dns if ip.version == 4]

        dhcp4_json = util.file.load_json("templates/kea/kea-dhcp4.conf")
        dhcp4_config = dhcp4_json["Dhcp4"]
        dhcp4_config["interfaces-config"]["interfaces"] = [fakeisp["name"]]
        dhcp4_config["ddns-update-on-renew"] = False
        dhcp4_config["subnet4"] = [{
            "subnet": str(subnet),
            "pools": [{"pool": str(subnet.network_address + vlan["dhcp_min_address_ipv4"])
                       + " - " + str(subnet.network_address + vlan["dhcp_max_address_ipv4"])}],
            "option-data": [{"name": "routers", "data": str(fakeisp["ipv4_address"])}],
            "dhcp-ddns": {"enable-updates": False}
        }]
        if dns:
            dhcp4_config["subnet4"][0]["option-data"].append({"name": "domain-name-servers", "data":  ", ".join(dns)})

        util.file.write("kea-dhcp4.conf", util.file.output_json(dhcp4_json), output_dir)
        setup.append("rootinstall $DIR/kea-dhcp4.conf /etc/kea")

        subnet = vlan["ipv6_subnet"]

        if subnet:
            dns = [str(ip) for ip in external_dns if ip.version == 6]

            dhcp6_json = util.file.load_json("templates/kea/kea-dhcp6.conf")
            dhcp6_config = dhcp6_json["Dhcp6"]
            dhcp6_config["interfaces-config"]["interfaces"] = [fakeisp["name"] + "/" + str(fakeisp["ipv6_address"])]
            dhcp6_config["ddns-update-on-renew"] = False
            dhcp6_config["subnet6"] = [{
                "subnet": str(subnet),
                "pools": [{"pool": str(subnet.network_address + vlan["dhcp_min_address_ipv6"])
                           + " - " + str(subnet.network_address + vlan["dhcp_max_address_ipv6"])}],
                "dhcp-ddns": {"enable-updates": False},
                "rapid-commit": True
            }]
            if dns:
                dhcp4_config["subnet6"][0]["option-data"] = [{"name": "dns-servers", "data":  ", ".join(dns)}]

            util.file.write("kea-dhcp6.conf", util.file.output_json(dhcp6_json), output_dir)
            setup.append("rootinstall $DIR/kea-dhcp6.conf /etc/kea")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0
