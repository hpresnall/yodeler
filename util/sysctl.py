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
    sysctl_conf.append("# also disable vlan parents, openvswitch uplinks & ports for vms\n")

    for iface in cfg["interfaces"]:
        if iface["ipv6_disabled"]:
            if iface["type"] == "port" and iface["subtype"] == "vswitch":
                # vswitch interfaces (and vswitch ports for vms) are not defined at boot
                # they will be handled via libvirt hook scripts
                continue
            if iface.get("subtype") == "vmhost":
                # vmhost interface switch ports are disabled using the local service since they do not exist until ifup
                continue

            disabled = True
            name = iface["name"]

            sysctl_conf.append(f"net.ipv6.conf.{name}.disable_ipv6 = 1")
            sysctl_conf.append(f"net.ipv6.conf.{name}.accept_ra = 0")
            sysctl_conf.append(f"net.ipv6.conf.{name}.autoconf = 0")
            sysctl_conf.append("")

            _logger.debug("disabling ipv6 for %s %s",  cfg["hostname"], iface["name"])

    if disabled:
        _create_file("ipv6_disable", sysctl_conf, setup, output_dir)


def enable_temp_addresses(cfg: dict, setup: shell.ShellScript, output_dir: str):
    addresses = False
    sysctl_conf = []
    sysctl_conf.append("# enable ipv6 temporary addresses")

    for iface in cfg["interfaces"]:
        if iface["ipv6_tempaddr"]:
            if iface["type"] not in {"std", "uplink"}:
                # do not enable for ports or vlan parents since they should have ipv6 disabled
                # do not enable for vlan interfaces because no traffic should originate from those ips
                continue
            if iface.get("subtype") == "vmhost":
                # vmhost interface switch ports are configured using the local service since they do not exist until ifup
                continue

            addresses = True
            name = iface["name"]

            sysctl_conf.append(f"net.ipv6.conf.{name}.use_tempaddr = 2")  # 2 =>use and prefer
            # use for 1 day, remove after 2
            # incorrect spelling is the valid value
            sysctl_conf.append(f"net.ipv6.conf.{name}.temp_prefered_lft = 86400")
            sysctl_conf.append(f"net.ipv6.conf.{name}.temp_valid_lft = 172800")
            sysctl_conf.append("")

            _logger.debug("enabling ipv6 temp addresses for %s %s",  cfg["hostname"], iface["name"])

    if addresses:
        _create_file("ipv6_temp_addr", sysctl_conf, setup, output_dir)


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

def enable_tcp_fastopen(setup: shell.ShellScript, output_dir: str):
    sysctl_conf = []
    sysctl_conf.append("# enable TCP fast open")

    sysctl_conf.append("net.ipv4.tcp_fastopen = 3\n")

    _create_file("tcp_fast_open", sysctl_conf, setup, output_dir)

def _create_file(name: str, sysctl_conf: list[str], setup: shell.ShellScript, output_dir: str):
    name += ".conf"
    file.write(name, "\n".join(sysctl_conf), output_dir)

    setup.append(f"rootinstall $DIR/{name} /etc/sysctl.d")
    setup.blank()

