"""Common configuration & setup for all Alpine hosts."""
import util.shell
import util.file
import util.interfaces
import util.awall
import util.resolv

from roles.role import Role


class Common(Role):
    """Common setup required for all systems. This role _must_ be run before any other setup."""

    def __init__(self):
        super().__init__("common")

    def additional_packages(self):
        # use Debian's better ifupdown and the Linux ip command, instead of Busybox's built-ins
        return {"ifupdown", "iproute2"}

    def additional_ifaces(self, cfg):
        return []

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
            common.append(util.awall.configure(cfg["interfaces"], output_dir))

        common.write_file(output_dir)

        util.file.write("interfaces", util.interfaces.as_etc_network(cfg["interfaces"]), output_dir)

        util.resolv.create_conf(cfg["interfaces"], cfg["primary_domain"], cfg["domain"],
                                cfg["local_dns"], cfg["external_dns"], output_dir)
        _create_chrony_conf(cfg, output_dir)

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
