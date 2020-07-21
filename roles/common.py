import os

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
