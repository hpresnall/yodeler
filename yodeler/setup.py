import logging
import os
import shutil
import importlib

import yodeler.config as config
import util.file as file
import util.shell as shell

import roles.common as common

_logger = logging.getLogger(__name__)


def load_all_configs(sites_dir, site_name):
    sites_dir = os.path.join(os.path.abspath(sites_dir), site_name)
    site_cfg = load_site_config(sites_dir)

    _logger.info("processing hosts for site '%s'", site_name)

    host_cfgs = {}
    for path in os.listdir(sites_dir):
        if path == "site.yaml":
            continue

        host_cfg = load_host_config(site_cfg, path)
        host_cfgs[host_cfg["hostname"]] = host_cfg

    return host_cfgs


def load_site_config(sites_dir):
    site_cfg = config.load_site_config(sites_dir)
    _logger.info("loaded config for site '%s' from %s", site_cfg["site"], sites_dir)
    return site_cfg


def load_host_config(site_cfg, host_path):
    host_cfg = config.load_host_config(site_cfg, host_path[:-5])  # remove .yaml
    _logger.info("loaded config for '%s' from %s", host_cfg["hostname"], os.path.basename(host_path))
    return host_cfg


def create_scripts_for_host(cfg, output_dir):
    host_dir = os.path.join(output_dir, cfg["hostname"])
    cfg["config_dir"] = host_dir

    if os.path.exists(host_dir):
        _logger.warn(f"removing existing host configuration at {host_dir}")
        shutil.rmtree(host_dir)

    _logger.info("creating setup scripts for %s", cfg["hostname"])

    # copy files from config directly
    shutil.copytree("config", host_dir)

    scripts = common.setup(cfg, host_dir)
    cfg["packages"] |= common.packages

    # load modules for each role
    # update packages
    modules = []
    for role in cfg["roles"]:
        _logger.info("loading module for %s role on %s", role, cfg["hostname"])
        try:
            mod = importlib.import_module("roles." + role)
            cfg["packages"] |= set(mod.packages)
            modules.append(mod)
        except ModuleNotFoundError:
            _logger.fatal("cannot load module for role %s; it should be in the roles directory", role)
            raise

    # create setup scripts for every role
    for mod in modules:
        try:
            scripts.extend(mod.setup(cfg, host_dir))
        except AttributeError:
            _logger.fatal("cannot run module for role %s; it should have a setup(cfg, dir) function", role)
            raise

    # all packages now known
    file.write("packages", " ".join(cfg["packages"]), host_dir)

    # create a setup script that sources all the other scripts
    setup_script = shell.ShellScript("setup.sh")
    setup_script.append_self_dir()
    setup_script.append_rootinstall()

    if not cfg["is_vm"]:
        # for physical servers, add packages manually
        # VMs will have packages installed as part of image creation
        setup_script.append("apk " + cfg["apk_opts"] + " add `cat $DIR/packages`")
        setup_script.append("")

    for script in scripts:
        setup_script.append(". $DIR/" + script)

    setup_script.write_file(host_dir)
