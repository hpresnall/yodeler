"""Handles parsing and validating host configuration from YAML files."""
import logging
import os
import shutil
import sys

import util.file as file
import util.shell as shell

import config.interface as interface

import roles.common

import ipaddress

_logger = logging.getLogger(__name__)


def load(site_cfg: dict, host_path: str) -> dict:
    """Load the given host YAML file from given path, using the existing site config.

    Return a configuration that is a combination of the site and host configuration.
    This merged configuration is valid for creating a set of scripts for a specific host.
    """
    if not host_path:
        raise ValueError("host_path cannot be empty")

    host_path = os.path.abspath(host_path)

    _logger.info("loading host config from '%s'", os.path.basename(host_path))

    host_yaml = file.load_yaml(host_path)

    if "hostname" in host_yaml:
        host_yaml["hostname"] = host_yaml.pop("hostname")
    else:
        host_yaml["hostname"] = os.path.basename(host_path)[:-5]  # remove .yaml

    host_cfg = validate(site_cfg, host_yaml)

    _logger.debug("loaded host '%s' from '%s'", host_cfg["hostname"], host_path)

    return host_cfg


def validate(site_cfg: dict, host_yaml: dict) -> dict:
    """Validate the given YAML formatted host configuration.

    Returns a configuration file that is a combination of the site and host configuration.
    This merged configuration is valid for creating a set of scripts for a specific host.
    """
    if site_cfg is None:
        raise ValueError("empty site config")
    if not isinstance(site_cfg, dict):
        raise ValueError("site config must be a dictionary")
    if len(site_cfg) == 0:
        raise ValueError("empty site config")

    if host_yaml is None:
        raise ValueError("empty host config")
    if not isinstance(host_yaml, dict):
        raise ValueError("host config must be a dictionary")
    if len(host_yaml) == 0:
        raise ValueError("empty host config")

    if "hostname" not in host_yaml:
        raise KeyError("hostname cannot be empty")
    if not isinstance(host_yaml["hostname"], str):
        raise KeyError("hostname must be a string")
    if not host_yaml["hostname"]:
        raise KeyError("hostname cannot be empty")

    # silently ignore attempts to overwrite site config
    host_yaml.pop("vswitches", None)

    # shallow copy site config; host values overwrite site values
    host_cfg = {**site_cfg, **host_yaml}

    _set_defaults(host_cfg)

    _configure_roles(host_cfg)

    for role in host_cfg["roles"]:
        role.configure_interfaces(host_cfg)
    interface.validate(host_cfg)

    for role in host_cfg["roles"]:
        role.additional_configuration(host_cfg)

    _configure_packages(site_cfg, host_yaml, host_cfg)

    site_cfg["hosts"][host_cfg["hostname"]] = host_cfg

    return host_cfg


def write_scripts(host_cfg: dict, output_dir: str):
    """Create the configuration scripts and files for host and write them to the given directory."""
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug(file.output_yaml(host_cfg))

    host_dir = os.path.join(output_dir, host_cfg["hostname"])

    _logger.info("creating setup scripts for '%s'", host_cfg["hostname"])

    if os.path.exists(host_dir):
        _logger.debug("removing existing host configuration scripts from '%s'", host_dir)
        shutil.rmtree(host_dir)
    os.mkdir(host_dir)

    # create a setup script that sources all the other scripts
    setup_script = shell.ShellScript("setup.sh")
    setup_script.append_self_dir()
    setup_script.append_rootinstall()

    setup_script.append(f"echo \"Setting up '{host_cfg['hostname']}'\"\n")

    # add all scripts from each role
    for role in host_cfg["roles"]:
        try:
            for script in role.create_scripts(host_cfg, host_dir):
                setup_script.append(". $DIR/" + script)
        except (TypeError, AttributeError):
            _logger.fatal(("cannot run create_scripts on class %s; "
                           "it should have a create_scripts(cfg, output_dir) function "
                           "that returns an iterable list of scripts"), role)
            raise

    setup_script.write_file(host_dir)

    if host_cfg["is_vm"]:
        _bootstrap_vm(host_cfg, host_dir)
    else:
        _bootstrap_physical(host_cfg, host_dir)

    _preview_dir(host_dir)


def _set_defaults(cfg: dict):
    for key in _REQUIRED_PROPERTIES:
        if key not in cfg:
            raise KeyError("{0} not defined".format(key))

    for key in DEFAULT_CONFIG:
        if key not in cfg:
            cfg[key] = DEFAULT_CONFIG[key]
    if "local_dns" not in cfg:
        cfg["local_dns"] = []
    # external_dns defined in DEFAULT_CONFIG

    # remove from script output if not needed
    if not cfg["install_private_ssh_key"]:
        cfg["private_ssh_key"] = ""

    for dns in cfg["local_dns"]:
        try:
            ipaddress.ip_address(dns)
        except:
            raise KeyError(f"invalid local_dns IP address {dns}") from None
    for dns in cfg["external_dns"]:
        try:
            ipaddress.ip_address(dns)
        except:
            raise KeyError(f"invalid external_dns IP address {dns}") from None


def _configure_roles(cfg: dict):
    # list of role names in yaml => list of Role subclass instances
    # Common _must_ be the first so it is configured and setup first
    role_names = set(cfg["roles"] if cfg.get("roles") is not None else [])
    cfg["roles"] = [roles.common.Common()]

    # for each role, load the module, then the class
    # instantiate the class and add addtional config
    for role_name in role_names:
        _logger.debug("loading role '%s' for '%s'", role_name, cfg["hostname"])

        role_name = role_name.lower()

        if role_name != "common":
            cfg["roles"].append(roles.role.load(role_name))

            # assume roles_to_hostnames is shared by site and all hosts
            if role_name not in cfg["roles_to_hostnames"]:
                cfg["roles_to_hostnames"][role_name] = []

            cfg["roles_to_hostnames"][role_name].append(cfg['hostname'])


def _configure_packages(site_cfg: dict, host_yaml: dict, host_cfg: dict):
    # manually merge packages use set for uniqueness and union/interection operations
    for key in ["packages", "remove_packages"]:
        site = site_cfg.get(key)
        host = host_yaml.get(key)

        if site is None and host is None:
            host_cfg[key] = set()
        elif site is None:
            host_cfg[key] = set(host)
        elif host is None:
            host_cfg[key] = set(site)
        else:
            # combine; host overwrites site
            host_cfg[key] = set(site)
            host_cfg[key] |= set(host)

    for role in host_cfg["roles"]:
        host_cfg["packages"] |= role.additional_packages(host_cfg)

    # update packages based on config
    if host_cfg["metrics"]:
        host_cfg["packages"].add("prometheus-node-exporter")

     # remove iptables if there is no local firewall
    if not host_cfg["local_firewall"]:
        host_cfg["remove_packages"] |= {"iptables", "ip6tables"}
        host_cfg["packages"].discard("awall")

    if not host_cfg["is_vm"]:
        # add cpufreq and other utils to real hosts
        host_cfg["packages"] |= {"util-linux", "cpufreqd", "cpufrequtils"}

    # resolve conflicts in favor of adding the package
    host_cfg["remove_packages"] -= host_cfg["packages"]

    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug("adding packages %s", host_cfg["packages"])
        _logger.debug("removing packages %s", host_cfg["remove_packages"])


def _bootstrap_physical(cfg: dict, output_dir: str):
    # boot with install media; run /media/<install_dev>/<site>/<host>/yodel.sh
    # setup.sh will run in the installed host via chroot
    yodel = shell.ShellScript("yodel.sh")
    yodel.append_self_dir()
    yodel.substitute("templates/physical/create_physical.sh", cfg)
    yodel.write_file(output_dir)

    # create Alpine setup answerfile
    # use external DNS for initial Alpine setup
    cfg["external_dns_str"] = " ".join(cfg["external_dns"])
    file.write("answerfile", file.substitute("templates/physical/answerfile", cfg), output_dir)


def _bootstrap_vm(cfg: dict, output_dir: str):
    # setup.sh will run in the VM via chroot
    yodel = shell.ShellScript("yodel.sh")
    yodel.append_self_dir()
    yodel.substitute("templates/vm/create_vm.sh", cfg)
    yodel.write_file(output_dir)

    # helper script to delete VM image & remove VM
    delete_vm = shell.ShellScript("delete_vm.sh")
    delete_vm.substitute("templates/vm/delete_vm.sh", cfg)
    delete_vm.write_file(output_dir)

    # helper script to start VM
    start_vm = shell.ShellScript("start_vm.sh")
    start_vm.substitute("templates/vm/start_vm.sh", cfg)
    start_vm.write_file(output_dir)


def _preview_dir(output_dir: str, line_count: int = sys.maxsize):
    """Debug function that recursively logs the content of all files in the given directory.
    By default logs the the whole file. Use the line_count to limit the number of lines output for each file."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    _logger.debug(output_dir)
    _logger.debug("")

    for file in os.listdir(output_dir):
        path = os.path.join(output_dir, file)

        if not os.path.isfile(path):
            _preview_dir(path, line_count)
            continue

        line_count = 0
        lines = [path + "\n"]

        with open(path) as file:
            for line in file:
                if line_count > line_count:
                    break

                line_count += 1
                lines.append(line)
        _logger.debug("".join(lines))


# properties that are unique and cannot be set as defaults
_REQUIRED_PROPERTIES = ["site_name", "hostname", "public_ssh_key"]

# accessible for testing
DEFAULT_CONFIG = {
    "is_vm": True,
    "vcpus": 1,
    "memory_mb": 128,
    "disk_size_mb": 256,
    "image_format": "raw",
    "vm_images_path": "/vmstorage",
    "root_dev": "/dev/sda",
    "root_partition": "3",  # default disk layout puts /root on /dev/sda3
    # configure a local firewall and metrics on all systems
    "local_firewall": True,
    "metrics": True,
    "motd": "",
    # do not install private ssh key on every host
    "install_private_ssh_key": False,
    # if not specified, no SSH access will be possible!
    "user": "nonroot",
    "password": "apassword",
    "timezone": "UTC",
    "keymap": "us us",
    "alpine_repositories": ["http://dl-cdn.alpinelinux.org/alpine/latest-stable/main", "http://dl-cdn.alpinelinux.org/alpine/latest-stable/community"],
    "external_ntp": ["0.pool.ntp.org", "1.pool.ntp.org", "2.pool.ntp.org", "3.pool.ntp.org"],
    "external_dns": ["8.8.8.8", "9.9.9.9", "1.1.1.1"],
    # top-level domain for the site
    "domain": "",
    # domain for the host when it has multiple interfaces; used for DNS search
    "primary_domain": "",
    # for physical servers, manually specify contents of /etc/network/interfaces
    # default blank => installer will prompt
    "install_interfaces": ""
}
