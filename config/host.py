"""Handles parsing and validating host configuration from YAML files."""
import logging
import os
import shutil
import sys
import ipaddress

import role.roles as roles

import util.file as file
import util.parse as parse
import util.dns as dns

import script.shell as shell

import config.aliases as aliases
import config.interfaces as interfaces
import config.disks as disks
import config.metrics as metrics

import script.disks

_logger = logging.getLogger(__name__)


def load(site_cfg: dict, host_path: str | None) -> dict:
    """Load the given host YAML file from given path, using the existing site config.

    Return a configuration that is a combination of the site and host configuration.
    This merged configuration is valid for creating a set of scripts for a specific host.
    """
    if not host_path:
        raise ValueError("host_path cannot be empty")

    host_path = os.path.abspath(host_path)

    _logger.info("loading host config from '%s'", os.path.basename(host_path))

    host_yaml = file.load_yaml(host_path)

    parse.set_default_string("hostname", host_yaml, os.path.basename(host_path)[:-5])  # remove .yaml

    host_cfg = validate(site_cfg, host_yaml)

    _logger.debug("loaded host '%s'", host_cfg["hostname"])

    return host_cfg


def validate(site_cfg: dict | str | None, host_yaml: dict | str | None) -> dict:
    """Validate the given YAML formatted host configuration.

    Returns a configuration file that is a combination of the site and host configuration.
    This merged configuration is valid for creating a set of scripts for a specific host.
    Exposed for testing. In normal usage this will be called as part of building the site.
    """
    site_cfg = parse.non_empty_dict("site_cfg", site_cfg)
    host_yaml = parse.non_empty_dict("host_yaml", host_yaml)

    # basic hostname validation
    # full validation happens after all hosts / aliases are parsed in site.py
    hostname = parse.non_empty_string("hostname", host_yaml, "host_yaml").lower()  # lowercase for consistency

    if dns.invalid_hostname(hostname):
        raise ValueError(f"invalid hostname '{hostname}'")
    if hostname in site_cfg["hosts"]:
        raise ValueError(f"duplicate hostname '{hostname}'")
    if (hostname == "site") or (hostname == "profile") or (hostname == "build"):
        raise ValueError(f"invalid hostname '{hostname}'")
    host_yaml["hostname"] = hostname

    # silently ignore attempts to overwrite site config
    host_yaml.pop("site_name", None)
    host_yaml.pop("vswitches", None)
    host_yaml.pop("firewall", None)
    host_yaml.pop("domain", None)
    host_yaml.pop("external_ntp", None)
    host_yaml.pop("external_dns", None)
    host_yaml.pop("external_hosts", None)
    host_yaml.pop("site_enable_metrics", None)
    host_yaml.pop("profile", None)

    # profile is dict of hostname -> overrides
    if site_cfg["profile"] and (hostname in site_cfg["profile"]):
        host_yaml["profile"] = site_cfg["profile"][hostname]
        host_yaml["profile_name"] = site_cfg["profile"]["name"]
    else:
        host_yaml["profile"] = {}

    # shallow copy site config; host values overwrite site values
    host_cfg = {**site_cfg, **host_yaml}

    # since site_cfg is shared with all host's config, all hosts can find other hosts
    site_cfg["hosts"][hostname] = host_cfg

    # order matters here
    # default values may change by role, so load roles first
    _load_roles(host_cfg)

    # then, set default config values
    _set_defaults(host_cfg)

    # next, add all interfaces before validating the configuration
    for role in host_cfg["roles"]:
        role.configure_interfaces()

        if role.name != "common":
            # uniquify all role names and role aliases
            aliases.make_unique(host_cfg, role)

    # validate the rest of the config
    interfaces.validate(host_cfg)
    interfaces.validate_renaming(host_cfg)
    disks.validate(host_cfg)
    metrics.validate(host_cfg)
    aliases.validate(host_cfg)

    # all other config is valid, now add additional config
    for role in host_cfg["roles"]:
        role.additional_configuration()

    # run after additional configuration to allow role.additional_packages() to use interfaces, aliases, etc
    _configure_packages(site_cfg, host_yaml, host_cfg)

    # note role.validate() is called _after_ all hosts are loaded in site.py
    # see _validate_full_site()

    del host_cfg["profile"]

    return host_cfg


def write_scripts(host_cfg: dict, output_dir: str):
    """Create the configuration scripts and files for the host and write them to the given directory."""
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug(file.output_yaml(host_cfg))

    host_dir = os.path.join(output_dir, host_cfg["hostname"])

    _logger.info("writing setup scripts for '%s'", host_cfg["hostname"])

    if os.path.exists(host_dir):
        _logger.debug("removing existing host configuration scripts from '%s'", host_dir)
        shutil.rmtree(host_dir)
    os.mkdir(host_dir)

    # create the base setup script used by all roles
    # this is the script that is run via chroot in yodel.sh
    setup = shell.ShellScript("setup.sh")
    setup.comment("DO NOT run this script directly! It will be run in a chrooted environment _after_ installing Alpine.")
    setup.comment("Run yodel.sh instead!")
    setup.blank()

    setup.append_self_dir()
    setup.add_log_function()  # setup_logging() added to yodel.sh
    setup.append_rootinstall()

    setup.comment("map SETUP_TMP from yodel.sh into this chroot")
    setup.append("SETUP_TMP=/tmp")
    setup.blank()

    setup.comment("load any envvars passed in from yodel.sh")
    setup.append("source $SETUP_TMP/envvars")
    setup.blank()

    # expose backup and restore dirs to roles
    if host_cfg["backup"]:
        if host_cfg["is_vm"]:
            # restore will be available in /tmp/backup via create_vm.sh's contributions to yodel.sh
            setup.comment("backup was copied to /tmp via fs-skel-dir in yodel.sh")
            setup.append("RESTORE_DIR=/tmp/backup")
        else:
            # restore will be copied into host's site dir via create_physical.sh's contributions to yodel.sh
            setup.comment("backup was copied to host in yodel.sh as part of the site configuration")
            setup.append(f"RESTORE_DIR=\"$SITE_DIR/backup/{host_cfg['hostname']}\"")

        setup.append(f"BACKUP_DIR={host_cfg['backup_dir']}")
        setup.blank()

    # append setup for each role
    for role in host_cfg["roles"]:
        name = role.name.upper()

        setup.append(f"echo \"########## {name} ##########\"")
        setup.append(f"log Configuring role {name}")
        setup.blank()

        try:
            role.write_config(setup, host_dir)
        except:
            _logger.fatal(("cannot run write_config for role '%s'"), role.name)
            raise

        setup.blank()

    setup.comment("not removing host's /tmp, just its contents")
    setup.append("rm -rf $SETUP_TMP/*")
    setup.blank()

    setup.write_file(host_dir)

    if host_cfg["backup"]:
        host_cfg["backup_script"].write_file(host_dir)

    # create yodel.sh after formatting chroot scripts
    _configure_before_and_after_chroot(host_cfg)

    if host_cfg["is_vm"]:
        _bootstrap_vm(host_cfg, host_dir)
    else:
        _bootstrap_physical(host_cfg, host_dir)

    _preview_dir(host_dir)


def validate_overridable_site_defaults(cfg: dict):
    # overlay the profile values into the site config, if any
    for key in DEFAULT_SITE_CONFIG.keys():
        if key in cfg["profile"]:
            cfg[key] = cfg["profile"][key]

    # ensure overridden default values are the correct type and arrays only contain strings
    parse.configure_defaults("site_yaml", DEFAULT_SITE_CONFIG, _DEFAULT_SITE_CONFIG_TYPES, cfg)

    cfg["alpine_repositories"] = parse.read_string_list(
        "alpine_repositories", cfg, f"site '{cfg['site_name']}'")


def _set_defaults(cfg: dict):
    # overlay the profile values into the host config, if any
    required_values = {}

    for key in _REQUIRED_PROPERTIES.keys():
        # overlay the profile values into the host config, if any
        if key in cfg["profile"]:
            cfg[key] = cfg["profile"][key]

        if key not in cfg:
            raise KeyError(f"{key} not defined in '{cfg['hostname']}'")

        required_values[key] = cfg[key]

    for key in DEFAULT_CONFIG.keys():
        if key in cfg["profile"]:
            cfg[key] = cfg["profile"][key]

    # also called in site.py; this call ensures overridden values from the host are also valid
    validate_overridable_site_defaults(cfg)

    # validate required properties and types
    parse.configure_defaults(cfg["hostname"], DEFAULT_CONFIG, _DEFAULT_CONFIG_TYPES, cfg)
    parse.configure_defaults(cfg["hostname"], required_values, _REQUIRED_PROPERTIES, cfg)

    # confirm lists contain only strings
    cfg["awall_disable"] = parse.read_string_list("awall_disable", cfg, f"'{cfg['hostname']}'")

    cfg["kernel_params"] = parse.read_string_list_plurals(
        {"kernel_param", "kernel_params"}, cfg, f"'{cfg['hostname']}'")
    cfg.pop("kernel_param", None)

    needs_site_build = False

    for role in cfg["roles"]:
        needs_site_build |= role.needs_build_image()

        if role.name == "vmhost":
            # vmhost is always configured like a physical server
            # nested VMs require a second Yodel from within an already running VM
            cfg["is_vm"] = False

    cfg["needs_site_build"] = needs_site_build

    # remove from script output if not needed
    if not cfg["install_private_ssh_key"]:
        cfg["private_ssh_key"] = ""

    # backup script all roles can contribute to
    if cfg["backup"]:
        cfg["backup_script"] = shell.ShellScript("backup.sh", errexit=False)
        cfg["backup_dir"] = "/backup"

        # vmhosts backup to the same directory that vms use for virtiofs backup disks
        if not cfg["is_vm"] and cfg["hostname"] in cfg["roles_to_hostnames"]["vmhost"]:
            cfg["backup_dir"] = f"{cfg['vm_images_path']}/backup/{cfg['hostname']}"
    else:
        cfg["backup_script"] = None

    if cfg["is_vm"]:
        vmhost = cfg.get("vmhost")

        # ensure non-empty string, but allow None
        # will validate that vmhost is valid in site.py after all hosts are loaded
        if isinstance(vmhost, str) and not vmhost:
            raise ValueError(f"'{cfg['hostname']}' vmhost value cannot be an empty string")

        cfg["vmhost"] = vmhost
    else:
        cfg["vmhost"] = None

        if " " in cfg["vm_images_path"]:
            raise ValueError(f"'{cfg['vm_images_pat']}' vm_images_path value cannot contain spaces")

        # physical installs need an interface configured to download APKs and a disk to install the OS
        parse.set_default_string("install_interfaces", cfg, """auto lo
iface lo inet loopback
auto eth0
iface eth0 inet dhcp""")

        if "install_interfaces" in cfg["profile"]:
            cfg["install_interfaces"] = cfg["profile"]["install_interfaces"]

        parse.non_empty_string("install_interfaces", cfg, cfg["hostname"])

    aliases.configure(cfg)


def _load_roles(cfg: dict):
    # list of role names in yaml => list of Role subclass instances

    # allow both 'role' and 'roles'; only store 'roles'
    role_names = set(parse.read_string_list_plurals({"role", "roles"}, cfg, "role for " + cfg["hostname"]))
    cfg.pop("role", None)

    # Common _must_ be the first so it is configured and setup first
    common = roles.load("common", cfg)
    cfg["roles"] = [common]
    role_names.discard("common")

    # router or fakeisp must be next so all interfaces are configured before other roles use them
    # vmhost renames existing interfaces
    ordered_roles = []

    if "router" in role_names:
        ordered_roles.append("router")
        role_names.discard("router")
    if "fakeisp" in role_names:
        ordered_roles.append("fakeisp")
        role_names.discard("fakeisp")
    if "vmhost" in role_names:
        ordered_roles.append("vmhost")
        role_names.discard("vmhost")

    ordered_roles.extend(role_names)

    for role_name in ordered_roles:
        _logger.debug("adding role '%s' to '%s'", role_name, cfg["hostname"])

        role_name = role_name.lower()
        role = roles.load(role_name, cfg)

        cfg["roles"].append(role)

        # assume roles_to_hostnames is shared by site and all hosts
        # note common role is _not_ added to this dict
        if role_name not in cfg["roles_to_hostnames"]:
            cfg["roles_to_hostnames"][role_name] = []

        cfg["roles_to_hostnames"][role_name].append(cfg['hostname'])


def _configure_packages(site_cfg: dict, host_yaml: dict, host_cfg: dict):
    # manually merge packages
    # use set for uniqueness and union/intersection operations
    for key in ["packages", "remove_packages"]:
        site = site_cfg.get(key)
        host = host_yaml.get(key)

        if site is None:
            site = set()
        if host is None:
            host = set()

        # combine; host overwrites site
        host_cfg[key] = set(site)
        host_cfg[key] |= set(host)

    for role in host_cfg["roles"]:
        host_cfg["packages"] |= role.additional_packages()

    # update packages required for metrics
    metrics.add_packages(host_cfg)

    # resolve conflicts in favor of adding the package
    host_cfg["remove_packages"] -= host_cfg["packages"]

    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug("adding packages %s", host_cfg["packages"])

        if host_cfg["remove_packages"]:
            _logger.debug("removing packages %s", host_cfg["remove_packages"])

    if host_cfg["enable_testing_repository"]:
        host_cfg["alpine_repositories"].append(host_cfg["alpine_testing_repository"])

def _configure_before_and_after_chroot(cfg: dict):
    # convert before & after chroot arrays into string for substitution in bootstrap scripts
    # handle top-level, unnested before & after chroot scripts differently for vms
    before = ""
    if cfg["before_chroot"]:
        before = _concat_and_indent(cfg["before_chroot"])
    if cfg["unnested_before_chroot"]:
        if cfg["is_vm"]:
            # only run if VM's yodel.sh is running unnested (i.e. reinstalling the vm from a running vm host)
            before += "if [ -z \"$NESTED_YODEL\" ]; then\n"
            before += _concat_and_indent(cfg["unnested_before_chroot"], indent="  ", extra_blank=False)
            before += "fi"
        else:
            # for physical servers, yodel.sh will always be unnested, so always run
            before += _concat_and_indent(cfg["unnested_before_chroot"])
    if before:
        # no ending blank lines
        while before.endswith("\n"):
            before = before[:-1]
        cfg["before_chroot"] = before
    else:
        cfg["before_chroot"] = "# no configuration needed before chroot"

    after = ""
    if cfg["unnested_after_chroot"]:
        if cfg["is_vm"]:
            # only run if VM's yodel.sh is running unnested (i.e. reinstalling the vm from a running vm host)
            after += "if [ -z \"$NESTED_YODEL\" ]; then\n"
            after += _concat_and_indent(cfg["unnested_after_chroot"], indent="  ", extra_blank=False)
            after += "fi"
        else:
            # for physical servers, yodel.sh will always be unnested, so always run
            after += _concat_and_indent(cfg["unnested_after_chroot"])
    if cfg["after_chroot"]:
        after += _concat_and_indent(cfg["after_chroot"])
    if after:
        # no ending blank lines
        while after.endswith("\n"):
            after = after[:-1]
        cfg["after_chroot"] = after
    else:
        cfg["after_chroot"] = "# no configuration needed after chroot"


def _bootstrap_physical(cfg: dict, output_dir: str):
    for disk in cfg["disks"]:
        if disk["name"] == "system":
            # system disk type must be 'device' per config allowed in disks.py
            cfg["system_dev"] = disk["path"]
            cfg["system_partition"] = disk["partition"]

            # for the actual Alpine install, use the real path of the disk
            # assume answerfile is sourced by installer and the shell will interpret the value
            cfg["system_dev_real"] = script.disks.get_real_path(disk)
            break

    # boot with install media; run /media/<install_dev>/<site>/<host>/yodel.sh
    # setup.sh will run in the installed host via chroot
    yodel = shell.ShellScript("yodel.sh")
    yodel.comment("Run this script to configure a Yodeler physical server")
    yodel.comment("Run in a booted Alpine Linux install image")
    yodel.blank()
    yodel.append_self_dir()
    yodel.substitute("physical", "ensure_writable.sh", cfg)
    yodel.setup_logging(cfg["hostname"])
    yodel.substitute("physical", "create_physical.sh", cfg)
    yodel.write_file(output_dir)

    # create Alpine setup answerfile
    # use external DNS for initial Alpine setup
    cfg["external_dns_str"] = " ".join([str(ip) for ip in cfg["external_dns"]])

    file.substitute_and_write("physical", "answerfile", cfg, output_dir)


def _bootstrap_vm(cfg: dict, output_dir: str):
    # setup.sh will run in the VM via alpine-make-vm-image's chroot
    yodel = shell.ShellScript("yodel.sh")
    yodel.comment("Run this script to configure a Yodeler VM")
    yodel.comment("Run in a KVM host configured by Yodeler")
    yodel.blank()
    yodel.append_self_dir()
    yodel.setup_logging(cfg["hostname"])
    yodel.substitute("vm", "create_vm.sh", cfg)
    yodel.write_file(output_dir)

    # helper script to delete VM image & remove VM
    delete_vm = shell.ShellScript("delete_vm.sh", errexit=False)
    delete_vm.substitute("vm", "delete_vm.sh", cfg)
    delete_vm.write_file(output_dir)

    # helper script to start VM
    start_vm = shell.ShellScript("start_vm.sh", errexit=False)
    start_vm.substitute("vm", "start_vm.sh", cfg)
    start_vm.write_file(output_dir)


def _concat_and_indent(data: list[str], indent="", extra_blank=True) -> str:
    concat = ""
    last_line_blank = False

    # loop rather than use join so empty lines are not indented
    for line in data:
        if line:
            if line == "\n":
                if not last_line_blank:
                    concat += line
                last_line_blank = True
            else:
                if line.endswith("\n"):
                    concat += indent + line
                else:
                    concat += indent + line + "\n"
                last_line_blank = False
        else:
            # only allow a single blank line
            if not last_line_blank:
                concat += "\n"
            last_line_blank = True

    # remove extra blank lines
    while concat.endswith("\n\n"):
        concat = concat[:-1]

    # add back if needed
    if extra_blank:
        concat += "\n"

    return concat


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
# usually set by the site and copied to the host
_REQUIRED_PROPERTIES = {"site_name": str, "public_ssh_key": str}

# site-level properties defined here since they should be checked when loading the site YAML _and_ for each host YAML
# accessible for testing
DEFAULT_SITE_CONFIG = {
    "timezone": "UTC",
    "keymap": "us us",
    "alpine_repositories": ["https://dl-cdn.alpinelinux.org/alpine/latest-stable/main", "https://dl-cdn.alpinelinux.org/alpine/latest-stable/community"],
    "alpine_testing_repository": "https://dl-cdn.alpinelinux.org/alpine/edge/testing",
    "enable_testing_repository": False,
    "external_ntp": ["0.pool.ntp.org", "1.pool.ntp.org", "2.pool.ntp.org", "3.pool.ntp.org"],
    "external_dns": [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("9.9.9.9"), ipaddress.ip_address("1.1.1.1")],
    # top-level domain for the site; empty => no local DNS unless DNS server sets 'primary_domain'
    "domain": "",
    # if not specified, no SSH access will be possible!
    "user": "nonroot",
    "password": "apassword",
    "site_enable_metrics": True  # disable metrics at the site level, regardless of the host's 'enable_metrics' value
}

_DEFAULT_SITE_CONFIG_TYPES = {
    "timezone": str,
    "keymap": str,
    "alpine_repositories": list,
    "alpine_testing_repository": str,
    "enable_testing_repository": bool,
    "external_ntp": list,
    "external_dns": list,
    "domain": str,
    "user": str,
    "password": str,
    "site_enable_metrics": bool
}

# accessible for testing
DEFAULT_CONFIG = {
    "is_vm": True,
    "vm_use_efi": False,
    "autostart": True,
    "host_share": True,
    "backup": True,
    "vcpus": 1,
    "memory_mb": 128,
    "disk_size_mb": 256,
    "vm_images_path": "/vmstorage",
    # configure a local firewall and metrics on all systems
    "local_firewall": True,
    "motd": "",
    # do not install private ssh key on every host
    "install_private_ssh_key": False,
    # domain for the host when it has multiple interfaces; used for DNS search
    "primary_domain": "",
    # by default, enable the watchdog service
    "enable_watchdog": True,
    "watchdog_dev": "/dev/watchdog",
    # list of service names to disable in awall firewall config
    "awall_disable": [],  # list of service names to disable in awall firewall config
    # scripts to run before chrooting into the host's install image
    # unnested will run outside the _vm host's_ install image when running setup for afull site
    "before_chroot": [],
    "after_chroot": [],
    "unnested_before_chroot": [],
    "unnested_after_chroot": [],
    "rename_interfaces": [],
    # Linux kernel command line parameters; allow singular and plural
    "kernel_params": [],
    # script to calculate parameters
    "setup_kernel_params": [],
    "enable_metrics": True  # allow metrics for this host?; separate from the metrics _role_ which is for collection
}

_DEFAULT_CONFIG_TYPES = {
    "is_vm": bool,
    "vm_use_efi": bool,
    "autostart": bool,
    "host_share": bool,  # on VMs, expose shared drive from KVM host? Drive will be shared by _all_ VMs on the host.
    "backup": bool,
    "vcpus": int,
    "memory_mb": int,
    "disk_size_mb": int,
    "vm_images_path": str,
    "local_firewall": bool,
    "motd": str,
    "install_private_ssh_key": bool,
    "primary_domain": str,
    "enable_watchdog": bool,
    "watchdog_dev": str,
    "awall_disable": list,
    "before_chroot": list,
    "after_chroot": list,
    "unnested_before_chroot": list,
    "unnested_after_chroot": list,
    "rename_interfaces": list,
    "kernel_params": list,
    "setup_kernel_params": list,
    "enable_metrics": bool
}
