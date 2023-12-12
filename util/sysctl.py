"""Utility functions for creating files in /etc/sysctl.d.
"""
import logging

import util.file as file
import util.shell as shell

_logger = logging.getLogger(__name__)


def disable_ipv6(cfg: dict, setup: shell.ShellScript, output_dir: str):
    disabled = False
    sysctl_conf = []
    sysctl_conf.append("# disable ipv6 on ipv4 only networks")
    sysctl_conf.append("# also disable vlan parents and openvswitch interfaces & uplinks\n")

    for iface in cfg["interfaces"]:
        if iface["ipv6_disabled"]:
            disabled = True
            name = iface["name"]

            sysctl_conf.append(f"net.ipv6.conf.{name}.disable_ipv6 = 1")
            sysctl_conf.append(f"net.ipv6.conf.{name}.accept_ra = 0")
            sysctl_conf.append(f"net.ipv6.conf.{name}.autoconf = 0")
            sysctl_conf.append("")

            _logger.debug("disabling ipv6 for %s %s",  cfg["hostname"], iface["name"])

    if disabled:
        _create_file("ipv6_disable", sysctl_conf, setup, output_dir)


def enable_ipv6_forwarding(setup: shell.ShellScript, output_dir: str):
    """Globally enable ipb6 forwarding by creating a sysctl.d conf file.
    This is required; ifupdown-ng currently only sets the value on each interface.
    """
    sysctl_conf = []
    sysctl_conf.append("# enable ipv6 forwarding globally")
    sysctl_conf.append(
        "# see https://unix.stackexchange.com/questions/348533/is-net-ipv6-conf-all-forwarding-1-equivalent-to-enabling-forwarding-for-all-indi\n")
    sysctl_conf.append("net.ipv6.conf.all.forwarding = 1\n")

    _create_file("ipv6_forwarding", sysctl_conf, setup, output_dir)

    _logger.debug("enabled ipv6 forwarding")


def _create_file(name: str, sysctl_conf: list[str], setup: shell.ShellScript, output_dir: str):
    name += ".conf"
    file.write(name, "\n".join(sysctl_conf), output_dir)

    setup.append(f"rootinstall $DIR/{name} /etc/sysctl.d")
    setup.blank()
