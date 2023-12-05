import shutil
import os
import logging
import ipaddress

from roles.role import Role

import config.vlan
import config.interface

import util.shell
import util.file

_logger = logging.getLogger(__name__)


class FakeISP(Role):
    def additional_packages(self) -> set[str]:
        return {"kea", "kea-dhcp4", "kea-dhcp6", "kea-admin", "kea-ctrl-agent", "kea-hook-run-script", "iptables", "ip6tables", "radvd"}

    def configure_interfaces(self):
        # ensure required vswitches and vlans exist
        if "fakeinternet" not in self._cfg["vswitches"]:
            raise ValueError(f"site '{self._cfg['site']}' does not define a 'fakeinternet' vswitch")
        if "fakeisp" not in self._cfg["vswitches"]:
            raise ValueError(f"site '{self._cfg['site']}' does not define a 'fakeisp' vswitch")

        # note vlan=fakeinet but vswitch=fakeinternet
        finet_vlan = config.vlan.lookup("fakeinet", self._cfg["vswitches"]["fakeinternet"])
        fisp_vlan = config.vlan.lookup("fakeisp", self._cfg["vswitches"]["fakeisp"])

        fisp_vlan["dhcp6_managed"] = True  # allow DHCP6 requests

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

        # act as router with well known address
        fakeisp["forward"] = True
        fakeisp.setdefault("ipv4_address", str(fisp_vlan["ipv4_subnet"].network_address + 1))

        if fisp_vlan.get("ipv6_subnet"):
            subnet = fisp_vlan["ipv6_subnet"]

            # for ipv6, subdivide into 2 seprate networks
            # the first will be used for this servers ip and DHCP; the second will be used for prefix delegation
            subnets = list(subnet.subnets())
            fisp_vlan["ipv6_subnet"] = subnets[0]
            fisp_vlan["ipv6_delegation_subnet"] = subnets[1]

            _logger.debug(
                f"splitting {subnet}; will use {subnets[0]} for server & DHCP address and {subnets[1]} for prefix delegation")

            fakeisp.setdefault("ipv6_address",  str(subnets[0].network_address + 1))
            # accept router advertisements, but do not use the local DHCP server
            fakeisp["accept_ra"] = True
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
        dhcp4_config["dhcp-ddns"] = {"enable-updates": False}
        dhcp4_config["ddns-update-on-renew"] = False
        dhcp4_config["subnet4"] = [{
            "subnet": str(subnet),
            "pools": [{"pool": str(subnet.network_address + vlan["dhcp_min_address_ipv4"])
                       + " - " + str(subnet.network_address + vlan["dhcp_max_address_ipv4"])}],
            "option-data": [{"name": "routers", "data": str(fakeisp["ipv4_address"])}]
        }]
        if dns:
            dhcp4_config["subnet4"][0]["option-data"].append({"name": "domain-name-servers", "data":  ", ".join(dns)})

        util.file.write("kea-dhcp4.conf", util.file.output_json(dhcp4_json), output_dir)
        setup.append("rootinstall $DIR/kea-dhcp4.conf /etc/kea")
        setup.service("kea-dhcp4")
        setup.blank()

        subnet = vlan["ipv6_subnet"]
        delegation_subnet = vlan["ipv6_delegation_subnet"]

        if subnet:
            dns = [str(ip) for ip in external_dns if ip.version == 6]

            dhcp6_json = util.file.load_json("templates/kea/kea-dhcp6.conf")
            dhcp6_config = dhcp6_json["Dhcp6"]
            dhcp6_config["interfaces-config"]["interfaces"] = [fakeisp["name"] + "/" + str(fakeisp["ipv6_address"])]
            dhcp6_config["dhcp-ddns"] = {"enable-updates": False}
            dhcp6_config["ddns-update-on-renew"] = False
            dhcp6_config["subnet6"] = [{
                "subnet": str(subnet),
                "pools": [{"pool": str(subnet.network_address + vlan["dhcp_min_address_ipv6"])
                           + " - " + str(subnet.network_address + vlan["dhcp_max_address_ipv6"])}],
                "pd-pools": _create_pd_pool(delegation_subnet),
                "rapid-commit": True,
                "interface": fakeisp["name"]
            }]
            if dns:
                dhcp4_config["subnet6"][0]["option-data"] = [{"name": "dns-servers", "data":  ", ".join(dns)}]

            # enabled shell script hook to update routes for prefix delegation
            dhcp6_config["hooks-libraries"] = {
                "library": "/usr/lib/kea/hooks/libdhcp_run_script.so",
                "parameters": {
                    "name": "usr/lib/kea/hooks/pdroute.sh"
                }
            }

            util.file.write("kea-dhcp6.conf", util.file.output_json(dhcp6_json), output_dir)

            setup.append("rootinstall $DIR/kea-dhcp6.conf /etc/kea")
            setup.service("kea-dhcp6")
            setup.blank()

        # setup radvd on the fakeisp interface
        radvd_template = util.file.read("templates/router/radvd.conf")
        radvd_template = radvd_template.format(fakeisp["name"], "on")  # AdvManagedFlag on => use DHCP6
        util.file.write("radvd.conf", radvd_template, output_dir)

        setup.append("rootinstall radvd.conf /etc")
        setup.service("radvd", "boot")
        setup.blank()

        # directly copy the kea hook script
        shutil.copyfile("templates/fakeisp/pdroute.sh", os.path.join(output_dir, "pdroute.sh"))
        setup.comment("allow kea to modify routes for prefix delegation")
        setup.append("echo \"permit nopass kea cmd /sbin/ip\" >> /etc/doas.d/doas.conf")
        setup.append("install -o kea -g kea -m 750 $DIR/pdroute.sh /usr/lib/kea/hooks/")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0


def _create_pd_pool(subnet: ipaddress.IPv6Network) -> list[dict]:
    prefixlen = subnet.prefixlen

    # prefix length determines the delegation size
    if prefixlen >= 62:
        # do not allow /63 or /64 prefix delegations; they are too small
        raise ValueError(f"cannot create prefix delegation pool from {subnet} when it has less than 2 bits available")
    elif prefixlen >= 60:
        delegation_size = 62
    elif prefixlen >= 56:
        delegation_size = 60
    elif prefixlen >= 48:
        delegation_size = 56
    else:
        # assume test environment; no need for more than 256 prefix delegations
        delegation_size = 56
        prefixlen = 48
        subnet = ipaddress.IPv6Network(str(subnet.network_address) + "/48")
        _logger.info(f"treating {subnet} as a /48 for prefix delegation")

    prefix_delegation_bits = delegation_size - prefixlen
    subnet_iter = subnet.subnets(prefixlen_diff=prefix_delegation_bits)

    if _logger.isEnabledFor(logging.DEBUG):
        subnets = list(subnet_iter)
        prefix_count = 2**prefix_delegation_bits
        _logger.debug(
            f"subnet {subnet} prefix delegation will have {prefix_count} /{delegation_size} networks; from {subnets[0]} to {subnets[-1]}")

        subnet_start = subnets[0]
    else:
        subnet_start = next(subnet_iter)

    return [{
        "prefix": str(subnet_start.network_address),
        "prefix-len": prefixlen,
        "delegated-len": delegation_size
    }]
