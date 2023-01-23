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

    def __init__(self, cfg: dict):
        super().__init__("ntp", cfg)

    def additional_packages(self):
        return set()  # create_chrony_conf() already called in common

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return 1

    def validate(self):
        missing_vlans = interface.check_accessiblity(self._cfg["interfaces"],
                                                     self._cfg["vswitches"].values())

        if missing_vlans:
            _logger.warning("vlans '%s' cannot access time from NTP host '%s'", self._cfg["hostname"], missing_vlans)

    def write_config(self, setup, output_dir):
        # create_chrony_conf() will be called by common
        pass


def create_chrony_conf(cfg, output_dir):
    buffer = []

    # use local NTP server if there is one defined
    if "ntp" in cfg["roles_to_hostnames"]:
        ntp_server_interfaces = cfg["hosts"][cfg["roles_to_hostnames"]["ntp"][0]]["interfaces"]
        ntp_addresses = interface.find_ips_to_interfaces(cfg, ntp_server_interfaces)
    else:
        ntp_addresses = []
        ntp_fqdn = None

    # if this is the ntp server, use the external addresses
    if ntp_addresses and (str(ntp_addresses[0]["ipv4_address"]) != "127.0.0.1"):
        for ntp in ntp_addresses:
            buffer.append(_pool_or_server(_find_address(ntp)))

        # just use the first address for boot setup
        buffer.append("")
        buffer.append(f"initstepslew 10 " + _find_address(ntp_addresses[0]))
    else:
        for server in cfg["external_ntp"]:
            buffer.append(_pool_or_server(server))

        buffer.append("")
        buffer.append(f"initstepslew 10 {cfg['external_ntp'][0]}")

    buffer.append("")
    buffer.append("driftfile /var/lib/chrony/chrony.drift")
    buffer.append("rtcsync")
    buffer.append("makestep 0.1 3")

    for role in cfg["roles"]:
        if role.name == "ntp":
            _configure_server(cfg, buffer)
            break

    util.file.write("chrony.conf", "\n".join(buffer), output_dir)


def _pool_or_server(ntp_server: str) -> str:
    if "pool" in ntp_server:
        return f"pool {ntp_server} iburst"
    else:
        return f"server {ntp_server} iburst"


def _find_address(ntp: dict) -> str:
    # prefer IPv4 for updates
    if "ipv4_address" in ntp:
        return str(ntp["ipv4_address"])
    else:
        return str(ntp["ipv6_address"])


def _configure_server(cfg: dict, buffer: list[str]):
    buffer.append("")

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
