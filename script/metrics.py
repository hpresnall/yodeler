"""Create shell script fragments for setting up Prometheus metrics."""
import script.shell as shell


def configure(cfg: dict, setup: shell.ShellScript, output_dir: str):
    if not cfg["metrics"]:
        return

    setup.log("Configuring Prometheus")
    setup.service("node-exporter")

    # default modules to enable for node exporter
    modules = ["cpu", "diskstats", "filefd", "filesystem", "meminfo", "netdev",
               "netstat", "schedstat", "sockstat", "stat", "udp_queues", "uname", "vmstat"]

    # additional modules for physical hosts
    if not cfg["is_vm"]:
        modules.extend(["edac", "hwmon", "nvme", "thermal_zone", "cpufreq", "nvme"])

    # additional modules for different roles
    for role in cfg["roles"]:
        if role.name == "router":
            modules.extend(["conntrack", "network_route"])
        if role.name == "vmhost":
            modules.extend(["cgroups"])
        if role.name == "storage":
            modules.extend(["nvme", "zfs"])

    modules = set(modules)

    # awful formatting; put each prometheus arg on a separate line ending with '\'
    # then, the whole command needs to be echoed to a file as a quoted param
    node_exporter_cmd = _PROMETHEUS_ARGS + " \\\n".join("--collector.%s" % c for c in sorted(modules))
    setup.append("echo \"ARGS=\\\"" + node_exporter_cmd + "\\\"\" > /etc/conf.d/node-exporter")
    setup.blank()

    _configure_libvirt(cfg, setup)


def _configure_libvirt(cfg: dict, setup: shell.ShellScript):
    if cfg["metrics"]["libvirt"]["enabled"]:
        setup.comment("collect libvirt metrics")
        setup.append("adduser prometheus libvirt")
        setup.service("libvirt-exporter")
        setup.blank()


_exporter_ports = {
    "node": 9100,
    "pdns": [9101, 9102],
    "libvirt": 9177,
    "nvme": 9105 # TODO update to actual value
}


def get_ports(metric_type: str) -> list[int] | int:
    return _exporter_ports[metric_type]


# ignore all ram, loop, floppy disks and all _partitions_
# ignore all non-file systems
_PROMETHEUS_ARGS = """--log.level=warn
--collector.diskstats.device-exclude='^(ram|loop|fd[a-z]|((h|s|v|xv)d[a-z]|nbd|sr|nvme\\\\d+n\\\\d+p))\\\\d+$' \\
--collector.filesystem.fs-types-exclude='^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tmpfs|tracefs)$' \\
--collector.disable-defaults \\
"""
