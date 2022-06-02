"""Common configuration & setup for all Alpine hosts."""
import os.path

import util.shell
import util.file
import util.interfaces
import util.libvirt
import util.awall
import util.resolv

from roles.role import Role


class Common(Role):
    """Common setup required for all systems. This role _must_ be run before any other setup."""

    def __init__(self):
        super().__init__("common")

    def additional_packages(self):
        # use better ifupdown-ng  and the Linux ip command, instead of Busybox's built-ins
        return {"ifupdown-ng", "iproute2"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        common = util.shell.ShellScript("common.sh")

        common.append("echo \"Running common config\"")
        common.append("")

        common.append(_setup_repos(cfg))

        if not cfg["is_vm"]:
            # for physical servers, add packages manually
            # VMs will have packages installed as part of image creation
            common.append("# install necessary packages")
            common.append("apk -q update")
            common.append("apk -q add $(cat $DIR/packages)")
            common.append("")

        # write all packages to a file; usage depends on vm or physical server
        util.file.write("packages", " ".join(cfg["packages"]), output_dir)

        # removing packages always handled by script
        cfg["remove_packages_str"] = " ".join(cfg["remove_packages"])

        common.substitute("templates/common/common.sh", cfg)

        if cfg["metrics"]:
            common.append(_SETUP_METRICS)

        if cfg["local_firewall"]:
            common.append(util.awall.configure(cfg["interfaces"], cfg["roles"], output_dir))

        common.write_file(output_dir)

        interfaces = [util.interfaces.loopback(), util.interfaces.from_config(cfg["interfaces"])]
        util.file.write("interfaces", "\n".join(interfaces), output_dir)

        util.resolv.create_conf(cfg["interfaces"], cfg["primary_domain"], cfg["domain"],
                                cfg["local_dns"], cfg["external_dns"], output_dir)
        _create_chrony_conf(cfg, output_dir)

        # different installation scripts for physical vs virtual
        if cfg["is_vm"]:
            _create_vm_script(cfg, output_dir)
            util.libvirt.write_vm_xml(cfg, output_dir)
        else:
            _create_bootstrap(cfg, output_dir)

        return [common.name]


def _setup_repos(cfg):
    repos = cfg["alpine_repositories"]
    buffer = []

    # overwrite on first, append on subsequent
    buffer.append("# setup APK repos")
    buffer.append(f"echo {repos[0]} > /etc/apk/repositories")

    repos = repos[1:]
    for repo in repos:
        buffer.append(f"echo {repo} >> /etc/apk/repositories")
    buffer.append("")

    return "\n".join(buffer)


def _create_chrony_conf(cfg, output_dir):
    buffer = []

    # use local NTP server if there is one defined
    if "local_ntp" in cfg:
        server = cfg["local_ntp"]
        buffer.append(f"server {server} iburst")
        buffer.append(f"initstepslew 10 {server}")
    else:
        servers = cfg["ntp_pool_servers"]
        for server in servers:
            buffer.append(f"server {server} iburst")
        buffer.append("initstepslew 10 {}".format(" ".join(servers)))

    buffer.append("driftfile /var/lib/chrony/chrony.drift")
    buffer.append("rtcsync")

    util.file.write("chrony.conf", "\n".join(buffer), output_dir)


def _create_bootstrap(cfg, output_dir):
    # expected flow: boot with install media; run /media/<install_dev>/bootstrap.sh
    # system reboots and runs local.d/setup.start

    # create Alpine install script
    install = util.shell.ShellScript("install_alpine.sh")
    install.append_self_dir()
    install.substitute("templates/alpine/install_alpine.sh", cfg)
    install.write_file(output_dir)

    # create Alpine setup answerfile
    # use external DNS for initial Alpine setup
    cfg["external_dns_str"] = " ".join(cfg["external_dns"])
    util.file.write("answerfile",
                    util.file.substitute("templates/alpine/answerfile", cfg), output_dir)

    # create bootstrap wrapper script
    bootstrap = util.shell.ShellScript("bootstrap.sh")
    bootstrap.append_self_dir()
    bootstrap.substitute("templates/common/bootstrap.sh", cfg)
    bootstrap.write_file(output_dir)

    # create local.d file that runs setup on first reboot after Alpine install
    setup = util.shell.ShellScript("setup.start")
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
    create_vm = util.shell.ShellScript("create_vm.sh")
    create_vm.append_self_dir()
    create_vm.substitute("templates/vm/create_vm.sh", cfg)
    create_vm.write_file(output_dir)

    # helper script to delete & remove VM
    delete_vm = util.shell.ShellScript("delete_vm.sh")
    delete_vm.substitute("templates/vm/delete_vm.sh", cfg)
    delete_vm.write_file(output_dir)


_SETUP_METRICS = """# setup Prometheus
rc-update add node-exporter default

echo "ARGS=\\\"--log.level=warn \\
--no-collector.bonding \\
--no-collector.btrfs \\
--no-collector.cpufreq \\
--no-collector.entropy \\
--no-collector.hwmon \\
--no-collector.ipvs \\
--no-collector.infiniband \\
--no-collector.nfs \\
--no-collector.nfsd \\
--no-collector.textfile \\
--no-collector.timex \\
--no-collector.xfs \\
--no-collector.zfs \\
--web.disable-exporter-metrics \\
--collector.diskstats.ignored-devices='^(ram|loop|fd|(h|s|v|xv)d[a-z]|nbd|sr|nvme\\\\d+n\\\\d+p)\\\\d+$' \\
--collector.filesystem.ignored-fs-types='^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tmpfs|tracefs|vfat)$'\\"" \\
> /etc/conf.d/node-exporter
"""
