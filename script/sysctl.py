"""Utility functions for creating files in /etc/sysctl.d or adding similar sysctl commands to shell scripts.
"""
import logging

import util.file as file

import script.shell as shell

_logger = logging.getLogger(__name__)


def disable_ipv6(cfg: dict, setup: shell.ShellScript, output_dir: str):
    disabled = False
    sysctl_conf = []
    sysctl_conf.append("# disable ipv6 on ipv4 only networks")
    sysctl_conf.append("# also disable vlan parents, openvswitch uplinks & ports for vms\n")

    for iface in cfg["interfaces"]:
        if iface["ipv6_disabled"]:
            if (iface["type"] == "port") and (iface["subtype"] == "vswitch"):
                # vswitch interfaces (and vswitch ports for vms) are not defined at boot
                # they will be handled via libvirt hook scripts
                continue
            if iface.get("subtype") == "vmhost":
                # vmhost interface switch ports are disabled using the local service since they do not exist until ifup
                continue

            disabled = True
            name = iface["name"]

            add_disable_ipv6_to_script(sysctl_conf, name, with_sysctl=False)
            sysctl_conf.append("")

            _logger.debug("disabling ipv6 for %s %s",  cfg["hostname"], name)

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

            add_tmpaddr_ipv6_to_script(sysctl_conf, name, with_sysctl=False)
            sysctl_conf.append("")

            _logger.debug("enabling ipv6 temp addresses for %s %s",  cfg["hostname"], name)

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


def add_disable_ipv6_to_script(script: shell.ShellScript | list[str], interface: str, indent="", with_sysctl: bool = True):
    if with_sysctl:
        script.append(f"{indent}sysctl -w net.ipv6.conf.{interface}.disable_ipv6=1")
        script.append(f"{indent}sysctl -w net.ipv6.conf.{interface}.accept_ra=0")
        script.append(f"{indent}sysctl -w net.ipv6.conf.{interface}.autoconf=0")
    else:
        script.append(f"{indent}net.ipv6.conf.{interface}.disable_ipv6 = 1")
        script.append(f"{indent}net.ipv6.conf.{interface}.accept_ra = 0")
        script.append(f"{indent}net.ipv6.conf.{interface}.autoconf = 0")


def add_tmpaddr_ipv6_to_script(script: shell.ShellScript | list[str], interface: str, indent="", with_sysctl: bool = True):
    if with_sysctl:
        script.append(f"{indent}sysctl -w net.ipv6.conf.{interface}.use_tempaddr=2")  # 2 =>use and prefer
        # use for 1 day, remove after 2
        # incorrect spelling is the valid value
        script.append(f"{indent}sysctl -w net.ipv6.conf.{interface}.temp_prefered_lft=86400")
        script.append(f"{indent}sysctl -w net.ipv6.conf.{interface}.temp_valid_lft=172800")
    else:
        script.append(f"{indent}net.ipv6.conf.{interface}.use_tempaddr = 2")
        script.append(f"{indent}net.ipv6.conf.{interface}.temp_prefered_lft = 86400")
        script.append(f"{indent}net.ipv6.conf.{interface}.temp_valid_lft = 172800")
