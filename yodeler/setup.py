"""Setup is responsible for loading all configuration for a given site.
It also creates the final, static set of configuration files for each host at the site.
"""
import logging
import os
import shutil
import xml.etree.ElementTree as xml

import yodeler.config as config

import util.file as file
import util.shell as shell

_logger = logging.getLogger(__name__)


def load_all_configs(sites_dir, site_name):
    """Load to configuration for all hosts defined in the given site.
    Return a map of hostnames to configurations."""
    sites_dir = os.path.join(os.path.abspath(sites_dir), site_name)
    site_cfg = _load_site_config(sites_dir)

    _logger.info("processing hosts for site '%s'", site_name)

    host_cfgs = {}
    for path in os.listdir(sites_dir):
        if path == "site.yaml":
            continue

        host_cfg = _load_host_config(site_cfg, path)
        host_cfgs[host_cfg["hostname"]] = host_cfg

    return host_cfgs


def _load_site_config(sites_dir):
    site_cfg = config.load_site_config(sites_dir)
    _logger.info("loaded config for site '%s' from %s", site_cfg["site"], sites_dir)
    return site_cfg


def _load_host_config(site_cfg, host_path):
    host_cfg = config.load_host_config(site_cfg, host_path[:-5])  # remove .yaml
    _logger.info("loaded config for '%s' from %s",
                 host_cfg["hostname"], os.path.basename(host_path))
    return host_cfg


def create_scripts_for_host(cfg, output_dir):
    """Create all the configuration scripts and files for the host
    and write them to the given directory."""
    host_dir = os.path.join(output_dir, cfg["hostname"])
    cfg["config_dir"] = host_dir

    if os.path.exists(host_dir):
        _logger.warning("removing existing host configuration at %s", host_dir)
        shutil.rmtree(host_dir)

    _logger.info("creating setup scripts for %s", cfg["hostname"])

    # copy files from config directly
    shutil.copytree("config", host_dir)

    # create a setup script that sources all the other scripts
    setup_script = shell.ShellScript("setup.sh")
    setup_script.append_self_dir()
    setup_script.append_rootinstall()

    setup_script.append(f"echo \"Setting up {cfg['hostname']}\"\n")

    # add all scripts from each role
    for role in cfg["roles"]:
        try:
            for script in role.create_scripts(cfg, host_dir):
                setup_script.append(". $DIR/" + script)
        except (TypeError, AttributeError):
            _logger.fatal(("cannot run create_scripts on class %s; "
                           "it should have a create_scripts(cfg, output_dir) function "
                           "that returns an iterable list of scripts"), role)
            raise

    setup_script.write_file(host_dir)

    # different installation scripts for physical vs virtual
    if cfg["is_vm"]:
        _create_vm_script(cfg, host_dir)
        _create_virsh_xml(cfg, host_dir)
    else:
        _create_bootstrap(cfg, host_dir)


def _create_bootstrap(cfg, output_dir):
    # expected flow: boot with install media; run /media/<install_dev>/bootstrap.sh
    # system reboots and runs local.d/setup.start

    # create Alpine install script
    install = shell.ShellScript("install_alpine.sh")
    install.append_self_dir()
    install.substitute("templates/alpine/install_alpine.sh", cfg)
    install.write_file(output_dir)

    # create Alpine setup answerfile
    # use external DNS for initial Alpine setup
    cfg["external_dns_str"] = " ".join(cfg["external_dns"])
    file.write("answerfile", file.substitute("templates/alpine/answerfile", cfg), output_dir)

    # create bootstrap wrapper script
    bootstrap = shell.ShellScript("bootstrap.sh")
    bootstrap.append_self_dir()
    bootstrap.substitute("templates/common/bootstrap.sh", cfg)
    bootstrap.write_file(output_dir)

    # create local.d file that runs setup on first reboot after Alpine install
    setup = shell.ShellScript("setup.start")
    setup.setup_logging(cfg["hostname"])

    # add contents of locald_setup.sh for each role
    for role in cfg["roles"]:
        path = os.path.join("templates", role.name, "locald_setup.sh")
        if os.path.exists(path) and os.path.isfile(path):
            setup.substitute(path, cfg)
    setup.write_file(output_dir)


def _create_vm_script(cfg, output_dir):
    # note not adding create_vm to setup script
    # for VMs, create_vm.sh will run setup _inside_ a chroot for the vm
    create_vm = shell.ShellScript("create_vm.sh")
    create_vm.append_self_dir()
    create_vm.substitute("templates/vm/create_vm.sh", cfg)
    create_vm.write_file(output_dir)

    # helper script to delete & remove VM
    delete_vm = shell.ShellScript("delete_vm.sh")
    delete_vm.substitute("templates/vm/delete_vm.sh", cfg)
    delete_vm.write_file(output_dir)


def _create_virsh_xml(cfg, output_dir):
    template = xml.parse("templates/vm/server.xml")
    domain = template.getroot()

    name = domain.find("name")
    name.text = cfg["hostname"]

    memory = domain.find("memory")
    memory.text = str(cfg["memory_mb"])

    vcpu = domain.find("vcpu")
    vcpu.text = str(cfg["vcpus"])

    devices = domain.find("devices")

    disk_source = devices.find("disk/source")
    disk_source.attrib["file"] = f"{cfg['vm_images_path']}/{cfg['hostname']}.img"

    for iface in cfg["interfaces"]:
        vlan_name = iface["vlan"]["name"]
        interface = xml.SubElement(devices, "interface")
        interface.attrib["type"] = "network"
        xml.SubElement(interface, "source",
                       {"network": iface["vswitch"]["name"], "portgroup": vlan_name})
        xml.SubElement(interface, "target", {"dev": f"{cfg['hostname']}-{vlan_name}"})
        xml.SubElement(interface, "model", {"type": "virtio"})

    template.write(os.path.join(output_dir, cfg["hostname"] + ".xml"))
