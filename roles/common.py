import os
import xml.etree.ElementTree as xml

import util.shell
import util.file
import util.interfaces
import util.awall
import util.resolv

# use Debian's better ifupdown and the Linux ip command, instead of Busybox's built-ins
packages = {"ifupdown", "iproute2"}


def setup(cfg, dir):
    common = util.shell.ShellScript("common.sh")

    common.append("echo \"Running common config\"")
    common.append("")

    common.append(_setup_repos(cfg))

    if not cfg["is_vm"]:
        # for physical servers, add packages manually
        # VMs will have packages installed as part of image creation
        common.append("# install necessary packages")
        common.append("apk -q update")
        common.append("apk -q add `cat $DIR/packages`")
        common.append("")

    cfg["remove_packages_str"] = " ".join(cfg["remove_packages"])
    common.append(util.file.substitute("templates/common/common.sh", cfg))

    if cfg["metrics"]:
        common.append(_setup_metrics)

    if cfg["local_firewall"]:
        common.append(util.awall.configure(cfg["interfaces"], dir))

    common.write_file(dir)

    util.file.write("interfaces", util.interfaces.as_etc_network(cfg["interfaces"]), dir)

    util.resolv.create_conf(cfg["interfaces"], cfg["primary_domain"], cfg["domain"],
                            cfg["local_dns"], cfg["external_dns"], dir)
    _create_chrony_conf(cfg, dir)

    if cfg["is_vm"]:
        # create the XML vm definition
        _create_virsh_xml(cfg, dir)

        # note not adding create_vm to setup script
        # for VMs, create_vm.sh will run setup _inside_ a chroot for the vm
        create_vm = util.shell.ShellScript("create_vm.sh")
        create_vm.append_self_dir()
        create_vm.append(util.file.substitute("templates/vm/create_vm.sh", cfg))
        create_vm.write_file(dir)

        # helper script to delete & remove VM
        delete_vm = util.shell.ShellScript("delete_vm.sh")
        delete_vm.append(util.file.substitute("templates/vm/delete_vm.sh", cfg))
        delete_vm.write_file(dir)
    else:
        # create Alpine setup answerfile for physical servers
        # use external DNS for initial Alpine setup
        cfg["external_dns_str"] = " ".join(cfg["external_dns"])
        util.file.write("answerfile", util.file.substitute("templates/alpine/answerfile", cfg), dir)

        install = util.shell.ShellScript("install_alpine.sh")
        install.append_self_dir()
        install.append(util.file.substitute("templates/alpine/install_alpine.sh", cfg))
        install.write_file(dir)
        # note not returning install script
        # it must be run manually by another process

    return [common.name]


def _setup_repos(cfg):
    repos = cfg["alpine_repositories"]
    b = []

    # overwrite on first, append on subsequent
    b.append("# setup APK repos")
    b.append(f"echo {repos[0]} > /etc/apk/repositories")

    repos = repos[1:]
    for r in repos:
        b.append(f"echo {r} >> /etc/apk/repositories")
    b.append("")

    return "\n".join(b)


def _create_chrony_conf(cfg, dir):
    b = []

    # use local NTP server if there is one defined
    if "local_ntp" in cfg:
        server = cfg["local_ntp"]
        b.append(f"server {server} iburst")
        b.append(f"initstepslew 10 {server}")
    else:
        servers = cfg["ntp_pool_servers"]
        for server in servers:
            b.append(f"server {server} iburst")
        b.append("initstepslew 10 {}".format(" ".join(servers)))

    b.append("driftfile /var/lib/chrony/chrony.drift")
    b.append("rtcsync")

    util.file.write("chrony.conf", "\n".join(b), dir)


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


_setup_metrics = """# setup Prometheus
rc-update add node-exporter default

echo "ARGS=\\\"--log.level=warn\
--no-collector.cpufreq\
--no-collector.entropy\
--no-collector.hwmon\
--no-collector.ipvs\
--no-collector.nfs\
--no-collector.nfsd\
--no-collector.textfile\
--no-collector.timex\
--no-collector.xfs\
--no-collector.zfs\
--web.disable-exporter-metrics\
--collector.diskstats.ignored-devices='^(ram|loop|fd|(h|s|v|xv)d[a-z]|nbd|sr|nvme\\d+n\\d+p)\\d+$'\
--collector.filesystem.ignored-fs-types='^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tmpfs|tracefs)$'\\\""\
> /etc/conf.d/node-exporter
"""
