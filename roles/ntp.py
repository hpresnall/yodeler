"""Configuration & setup for a Chrony NTP server."""
import logging

import util.shell
import util.file
import util.address

import config.interface as interface

from roles.role import Role

_logger = logging.getLogger(__name__)


class NTP(Role):
    """NTP defines the configuration needed to setup Chrony NTP."""

    def additional_packages(self):
        return set()  # create_chrony_conf() already called in common

    def additional_configuration(self):
        self.add_alias("time")
        self.add_alias("sntp")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return 2 # no need for additional redundancy

    def validate(self):
        for iface in self._cfg["interfaces"]:
            if (iface["type"] == "std") and (iface["ipv4_address"] == "dhcp"):
                raise KeyError(
                    f"host '{self._cfg['hostname']}' cannot configure aN NTP server with a DHCP address on interface '{iface['name']}'")

        missing_vlans = interface.check_accessiblity(self._cfg["interfaces"],
                                                     self._cfg["vswitches"].values())

        if missing_vlans:
            _logger.warning("vlans '%s' cannot access time from NTP host '%s'", self._cfg["hostname"], missing_vlans)

    def write_config(self, setup: util.shell.ShellScript, output_dir: str):
        # create_chrony_conf() will be called by common
        setup.comment("set in chrony.conf; no additional config needed")


def create_chrony_conf(cfg: dict, output_dir: str):
    buffer = []

    # use local NTP server if there is one defined
    ntp_addresses = []
    if "ntp" in cfg["roles_to_hostnames"]:
        for ntp_server in cfg["roles_to_hostnames"]["ntp"]:
            ntp_server_interfaces = cfg["hosts"][ntp_server]["interfaces"]
            ntp_addresses.extend(interface.find_ips_to_interfaces(cfg, ntp_server_interfaces))
    # else external_ntp will always be defined so chrony.conf will always be valid

    # do not run initstepslew at boot
    # for the router since dns will not be up
    # for vmhost since dns and the router will not be up
    at_boot = True
    for role in cfg["roles"]:
        if role.name in {"router", "vmhost"}:
            at_boot = False
            break

    if ntp_addresses:
        boot_address = None

        for ntp_address in ntp_addresses:
            # if this is the ntp server, stop and use the external addresses
            # do not attempt to use any other ntp servers in the site
            # assume localhost for ipv4 => localhost for ipv6 and
            if (str(ntp_address["ipv4_address"]) == "127.0.0.1"):
                buffer = []
                boot_address = None
                break

            if "ipv4_address" in ntp_address:
                buffer.append(f"server {str(ntp_address['ipv4_address'])} iburst")

                # just use the first ipv4 address for boot setup
                if not boot_address:
                    boot_address = str(ntp_address["ipv4_address"])

            if "ipv6_address" in ntp_address:
                buffer.append(f"server {str(ntp_address['ipv6_address'])} iburst")

        if at_boot and boot_address:
            buffer.append("")
            buffer.append(f"initstepslew 10 " + boot_address)

    if not buffer:
        for server in cfg["external_ntp"]:
            if "pool" in server:  # external ntp hostnames may be "pools" with multiple CNAMES
                buffer.append(f"pool {server} iburst")
            else:
                buffer.append(f"server {server} iburst")

        if at_boot:
            # just use the first server
            external = cfg['external_ntp'][0]
            buffer.append("")
            buffer.append(f"initstepslew 10 {external}")

    buffer.append("")
    buffer.append("driftfile /var/lib/chrony/chrony.drift")
    buffer.append("rtcsync")
    buffer.append("makestep 0.1 3")
    buffer.append("")

    for role in cfg["roles"]:
        if role.name == "ntp":
            _configure_server(cfg, buffer)
            break

    util.file.write("chrony.conf", "\n".join(buffer), output_dir)


def _configure_server(cfg: dict, buffer: list[str]):
    for iface in cfg["interfaces"]:
        if iface["type"] not in {"std", "vlan"}:
            continue

        if iface["vlan"]["routable"]:
            for vlan in iface["vswitch"]["vlans"]:
                if vlan["routable"]:  # router will make all routable vlans accessible
                    buffer.append("allow " + str(vlan["ipv4_subnet"]))

                    if vlan["ipv6_subnet"]:
                        buffer.append("allow " + str(vlan["ipv6_subnet"]))
        else:  # non-routable vlans must have an interface on the vlan
            buffer.append("allow " + str(iface["vlan"]["ipv4_subnet"]))

            if iface["vlan"]["ipv6_subnet"]:
                buffer.append("allow " + str(iface["vlan"]["ipv6_subnet"]))

    buffer.append("")
