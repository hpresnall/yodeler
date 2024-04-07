"""Configuration & setup for a Chrony NTP server."""
import logging

from role.roles import Role

import script.shell as shell

import config.interfaces as interfaces

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
        return 2  # no need for additional redundancy

    def validate(self):
        for iface in self._cfg["interfaces"]:
            if (iface["type"] == "std") and (iface["ipv4_address"] == "dhcp"):
                raise KeyError(
                    f"host '{self._cfg['hostname']}' cannot configure aN NTP server with a DHCP address on interface '{iface['name']}'")

        missing_vlans = interfaces.check_accessiblity(self._cfg["interfaces"],
                                                      self._cfg["vswitches"].values())

        if missing_vlans:
            _logger.warning("vlans '%s' cannot access time from NTP host '%s'", self._cfg["hostname"], missing_vlans)

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        # chrony.create_conf() will be called by common
        setup.comment("set in chrony.conf; no additional config needed")
