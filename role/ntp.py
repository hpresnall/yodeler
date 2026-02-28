"""Configuration & setup for a Chrony NTP server."""
import logging

from role.roles import Role

import script.shell as shell

import config.interfaces as interfaces
import config.firewall as fw

_logger = logging.getLogger(__name__)


class NTP(Role):
    """NTP defines the configuration needed to setup Chrony NTP."""

    def additional_packages(self) -> set[str]:
        return set()  # create_chrony_conf() already called in common

    def additional_aliases(self) -> list[str]:
        return ["time", "sntp"]

    def additional_configuration(self):
        # allow all routable vlans NTP access to this host on all its interfaces
        hostname = self._cfg["hostname"]
        destinations = fw.destinations_from_interfaces(self._cfg["interfaces"], hostname)

        if destinations:
            fw.add_rule(self._cfg, [fw.location_all()], destinations, [fw.allow_service("ntp")], f"NTP for {hostname}")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return 2  # no need for additional redundancy

    def validate(self):
        for iface in self._cfg["interfaces"]:
            if (iface["type"] == "std") and (iface["ipv4_address"] == "dhcp"):
                raise KeyError(
                    f"host '{self._cfg['hostname']}' cannot configure an NTP server with a DHCP address on interface '{iface['name']}'")

        missing_vlans = interfaces.check_accessiblity(self._cfg["interfaces"],
                                                      self._cfg["vswitches"].values())

        if missing_vlans:
            raise ValueError(
                f"host '{self._cfg['hostname']}' does not have access to vlans {missing_vlans} to provide DNS")

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        # chrony.create_conf() will be called by common
        setup.comment("set in chrony.conf; no additional config needed")
