import logging
import os
import shutil
import importlib
import xml.etree.ElementTree as xml

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

    setup_script.append(f"echo \"Setting up {cfg['hostname']}\"\n")

    for script in scripts:
        setup_script.append(". $DIR/" + script)

    setup_script.write_file(host_dir)

    # final configuration known, now create installation script
    if cfg["is_vm"]:
        # create the XML vm definition
        _create_virsh_xml(cfg, host_dir)

        # note not adding create_vm to setup script
        # for VMs, create_vm.sh will run setup _inside_ a chroot for the vm
        create_vm = shell.ShellScript("create_vm.sh")
        create_vm.append_self_dir()
        create_vm.append(file.substitute("templates/vm/create_vm.sh", cfg))
        create_vm.write_file(host_dir)

        # helper script to delete & remove VM
        delete_vm = shell.ShellScript("delete_vm.sh")
        delete_vm.append(file.substitute("templates/vm/delete_vm.sh", cfg))
        delete_vm.write_file(host_dir)
    else:
        # expected flow: boot with install media; run /media/<install_dev>/bootstrap.sh
        # system reboots and runs local.d/setup.start

        # create install script
        install = shell.ShellScript("install_alpine.sh")
        install.append_self_dir()
        install.append(file.substitute("templates/alpine/install_alpine.sh", cfg))
        install.write_file(host_dir)

        # create Alpine setup answerfile for physical servers
        # use external DNS for initial Alpine setup
        cfg["external_dns_str"] = " ".join(cfg["external_dns"])
        file.write("answerfile", file.substitute("templates/alpine/answerfile", cfg), host_dir)

        # create bootstrap wrapper script
        bootstrap = shell.ShellScript("bootstrap.sh")
        bootstrap.append_self_dir()
        bootstrap.append(file.substitute("templates/common/bootstrap.sh", cfg))
        bootstrap.write_file(host_dir)

        # create local.d file that runs setup on first reboot after Alpine install
        setup = shell.ShellScript("setup.start")
        setup.setup_logging(cfg["hostname"])
        setup.append(file.substitute("templates/common/locald_setup.sh", cfg))
        # each role can add setup
        for role in cfg["roles"]:
            path = os.path.join("templates", role, "locald_setup.sh")
            if os.path.exists(path) and os.path.isfile(path):
                setup.append(file.substitute(path, cfg))
        setup.write_file(host_dir)


def _create_virsh_xml(cfg, dir):
    template = xml.parse("templates/vm/server.xml")
    vm = template.getroot()

    name = vm.find("name")
    name.text = cfg["hostname"]

    memory = vm.find("memory")
    memory.text = str(cfg["memory_mb"])

    vcpu = vm.find("vcpu")
    vcpu.text = str(cfg["vcpus"])

    devices = vm.find("devices")

    disk_source = devices.find("disk/source")
    disk_source.attrib["file"] = f"{cfg['vm_images_path']}/{cfg['hostname']}.img"

    for iface in cfg["interfaces"]:
        vlan_name = iface["vlan"]["name"]
        interface = xml.SubElement(devices, "interface")
        interface.attrib["type"] = "network"
        xml.SubElement(interface, "source", {"network": iface["vswitch"]["name"], "portgroup": vlan_name})
        xml.SubElement(interface, "target", {"dev": f"{cfg['hostname']}-{vlan_name}"})
        xml.SubElement(interface, "model", {"type": "virtio"})

    template.write(os.path.join(dir, cfg["hostname"] + ".xml"))
