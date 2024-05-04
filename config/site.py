"""Site is responsible for loading all configuration for a given site.
It also creates the final, static set of configuration files for each host at the site.
"""
import logging
import os
import copy
import errno
import ipaddress

import role.roles as roles

import config.vswitch as vswitch
import config.firewall as firewall
import config.host as host

import util.file as file
import util.parse as parse

import script.shell as shell


_logger = logging.getLogger(__name__)


def load(site_dir: str | None, profile_name: str | None = None) -> dict:
    """Load 'site.yaml' from the given directory and validate it. If a profile is specified,
    first overlay the profile's information. This method also loads and validates all the host's
    configuration yaml files for the site.

    Return the site configuration that can be used in a subsequent call to write_host_scripts().
    """
    if not site_dir:
        raise ValueError("site_dir cannot be empty")

    site_dir = os.path.abspath(site_dir)

    _logger.info("loading site config from '%s'", site_dir)

    site_yaml = file.load_yaml(os.path.join(site_dir, "site.yaml"))

    site_yaml["site_name"] = os.path.basename(site_dir)

    if profile_name:
        parse.non_empty_string("name", {"name": profile_name}, "profile")
        profile_yaml = file.load_yaml(os.path.join(site_dir, f"profile_{profile_name}.yaml"))
        _logger.info("using profile '%s' to configure site '%s'", profile_name, site_yaml["site_name"])
        site_yaml["profile"] = profile_yaml
        site_yaml["profile"]["name"] = profile_name
        site_yaml["site_name"] += "-" + profile_name
    else:
        site_yaml.pop("profile", None)

    site_cfg = validate(site_yaml)

    _load_all_hosts(site_cfg, site_dir)

    _logger.debug("loaded site '%s' from '%s'", site_cfg["site_name"], site_dir)

    return site_cfg


def validate(site_yaml: dict | str | None) -> dict:
    """Validate the given YAML formatted site configuration.

    This configuration _is not_ valid for creating a set of scripts for a specific host.
    Instead, this configuration must be used as the base for loading host YAML files.
    """
    site_yaml = parse.non_empty_dict("site_yaml", site_yaml)

    parse.non_empty_string("site_name", site_yaml, "site_yaml")

    site_cfg = copy.deepcopy(site_yaml)

    host.validate_site_defaults(site_cfg)

    # order matters here; vswitch / vlans first since the firewall config needs that information
    vswitch.validate(site_cfg)
    firewall.validate(site_cfg)
    _validate_additional_dns_entries(site_cfg)

    # map hostname to host config
    site_cfg["hosts"] = {}

    # map roles to fully qualified domain names; shared with host configs
    site_cfg["roles_to_hostnames"] = {}
    for role in roles.names():
        site_cfg["roles_to_hostnames"][role] = []

    return site_cfg


def _load_all_hosts(site_cfg: dict, site_dir: str):
    """Load and validate all host YAML files for the given site."""
    _logger.debug("loading hosts for site '%s'", site_cfg["site_name"])

    total_vms = 0
    total_vcpus = 0
    total_mem = 0
    total_disk = 0

    for host_path in os.listdir(site_dir):
        if (host_path == "site.yaml") or (host_path.startswith("profile")):
            continue
        if not host_path.endswith(".yaml"):
            _logger.debug("skipping file %s", host_path)
            continue

        host_cfg = host.load(site_cfg, os.path.join(site_dir, host_path))

        if host_cfg["is_vm"]:
            total_vms += 1
            total_vcpus += host_cfg["vcpus"]
            total_mem += host_cfg["memory_mb"]

            for disk in host_cfg["disks"]:
                if disk["type"] == "img":
                    total_disk += disk["size_mb"]

    _validate_full_site(site_cfg)

    if total_vms > 0:
        _logger.info("loaded %d hosts for site '%s'", len(site_cfg["hosts"]), site_cfg["site_name"])
        _logger.info("total VM resources used: %d vcpus, %d GB memory & %d GB disk",
                     total_vcpus, round(total_mem / 1024), round(total_disk / 1024))


def write_host_scripts(site_cfg: dict, output_dir: str):
    """Create the configuration scripts and files for the site's hosts and write them to the given directory."""
    output_dir = os.path.join(output_dir, site_cfg["site_name"])

    _logger.info("writing setup scripts for site '%s' to '%s'", site_cfg["site_name"], output_dir)

    try:
        os.makedirs(output_dir)
    except OSError as ose:
        if ose.errno == errno.EEXIST and os.path.isdir(output_dir):
            pass
        else:
            raise ose

    needs_site_build = False
    vmhosts = []

    for host_cfg in site_cfg["hosts"].values():
        # configure vmhosts last so they have access to all their vm's chroot scripts
        if (host_cfg["hostname"] in site_cfg["roles_to_hostnames"]["vmhost"]):
            vmhosts.append(host_cfg)
            continue

        host.write_scripts(host_cfg, output_dir)
        needs_site_build |= host_cfg["needs_site_build"]

    for host_cfg in vmhosts:
        host.write_scripts(host_cfg, output_dir)
        needs_site_build |= host_cfg["needs_site_build"]

    if needs_site_build:
        _setup_site_build_scripts(site_cfg, output_dir)


def _validate_full_site(site_cfg: dict):
    # confirm site contains all necessary roles
    for role_name in roles.names():
        if role_name == "common":
            continue

        hostnames = site_cfg["roles_to_hostnames"][role_name] if role_name in site_cfg["roles_to_hostnames"] else []
        count = len(hostnames)

        clazz = roles.class_for_name(role_name)
        min = clazz.minimum_instances(site_cfg)
        max = clazz.maximum_instances(site_cfg)

        if count < min:
            raise ValueError((f"site '{site_cfg['site_name']}' requires at least {min} hosts with '{role_name}' role;"
                              f" {count} hosts defined: {hostnames}"))
        if count > max:
            raise ValueError((f"site '{site_cfg['site_name']}' requires no more than {max} hosts with '{role_name}' role;"
                              f" {count} hosts defined: {hostnames}"))

    # hostname uniqueness already determined as hosts were loaded but _not_ against all aliases; see host.validate()
    aliases = set()

    for host_cfg in site_cfg["hosts"].values():
        aliases.update(host_cfg["aliases"])  # this includes role names for the host

        hostname = host_cfg["hostname"]

        if hostname in aliases:
            raise KeyError(f"hostname '{hostname}' cannot be the same as another host's alias")
        aliases.add(host_cfg["hostname"])

        # validate here to avoid an additional all hosts loop
        for role in host_cfg["roles"]:
            role.validate()

        # set the host's VM host
        if host_cfg["is_vm"]:
            # TODO allow setting vmhost in config; will need to validate it
            host_cfg["vmhost"] = host_cfg["roles_to_hostnames"]["vmhost"][0]

    _logger.debug("all_aliases=%s", aliases)

    # finally, confirm that all the firewall rules point to valid hostnames
    firewall.validate_rule_hostnames(site_cfg)


def _validate_additional_dns_entries(cfg: dict):
    if not "additional_dns_entries" in cfg:
        cfg["additional_dns_entries"] = []
        return

    additional_dns = cfg["additional_dns_entries"]
    location = "additional_dns_entries"

    if not isinstance(additional_dns, list):
        raise ValueError(f"{location} must be a list")

    for i, entry in enumerate(additional_dns, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"{location}[{i}] must be a dict")

        entry["hostnames"] = parse.read_string_list_plurals({"hostname", "hostnames"}, entry, location)
        entry.pop("hostname", None)

        if "ipv4_address" not in entry:
            raise KeyError(f"{location} must specify an ipv4_address")
        try:
            entry["ipv4_address"] = ipaddress.ip_address(entry["ipv4_address"])
        except ValueError as ve:
            raise KeyError(f"invalid ipv4_address for {location}") from ve

        if "ipv6_address" in entry:
            try:
                entry["ipv6_address"] = ipaddress.ip_address(entry["ipv6_address"])
            except ValueError as ve:
                raise KeyError(f"invalid ipv6_address for {location}") from ve


def _setup_site_build_scripts(cfg: dict, output_dir: str):
    build_dir = os.path.join(output_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    # patch for alpine-make-vm-image if it exists
    # vms do not need this since they will use an already configured build image
    if os.path.isfile("templates/physical/make-vm-image-patch"):
        file.copy_template("physical", "make-vm-image-patch", build_dir)

    file.substitute_and_write("common", "setup_site_build.sh", cfg, build_dir)

    # helper script to unmount the build_image
    unmount_build = shell.ShellScript("unmount_site_build.sh")
    unmount_build.append(f"SITE_BUILD_MOUNT=\"/media/{cfg['site_name']}_build\"")
    unmount_build.blank()
    unmount_build.append("umount $SITE_BUILD_MOUNT/tmp/apk_cache")
    unmount_build.append("umount $SITE_BUILD_MOUNT")
    unmount_build.blank()
    unmount_build.append("echo \"Unmounted $SITE_BUILD_MOUNT\"")
    unmount_build.write_file(build_dir)
