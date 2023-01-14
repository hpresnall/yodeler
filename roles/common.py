"""Common configuration & setup for all Alpine hosts."""
import os.path
import shutil

import util.shell
import util.file
import util.interfaces
import util.libvirt
import util.awall
import util.resolv
import util.dhcpcd

from roles.role import Role


class Common(Role):
    """Common setup required for all systems. This role _must_ be run before any other setup."""

    def __init__(self, cfg: dict):
        super().__init__("common", cfg)

    def additional_packages(self):
        # use dhcpcd for dhcp since it can also handle prefix delegation for routers
        # use better ifupdown-ng  and the Linux ip command, instead of Busybox's built-ins
        packages = {"e2fsprogs", "acpi", "doas", "openssh", "chrony", "awall", "dhcpcd", "ifupdown-ng", "iproute2"}

        for iface in self._cfg["interfaces"]:
            if iface["name"].startswith("wlan"):
                packages.add("ifupdown-ng-wifi")
                break

        return packages

    def additional_configuration(self):
        self._cfg["fqdn"] = ""
        if ("prmary_domain" in self._cfg) and (self._cfg["prmary_domain"]):
            self._cfg["fqdn"] = self._cfg["hostname"] + '.' + self._cfg["prmary_domain"]

    def write_config(self, setup, output_dir):
        # write all packages to a file; usage depends on vm or physical server
        util.file.write("packages", " ".join(self._cfg["packages"]), output_dir)

        if not self._cfg["is_vm"]:
            # for physical servers, add packages manually
            _setup_repos(self._cfg, setup)
            _apk_update(setup)
            setup.append("echo \"Installing required packages\"")
            setup.append("apk -q --no-progress add $(cat $DIR/packages)")
            setup.blank()
        else:
            # VMs will use host's configured repo file and have packages installed as part of image creation
            _apk_update(setup)

            # VMs are setup without USB, so remove the library
            self._cfg["remove_packages"].add("libusb")

        if (self._cfg["remove_packages"]):
            setup.append("echo \"Removing unneeded packages\"")
            setup.append("apk -q del " + " ".join(self._cfg["remove_packages"]))
            setup.blank()

        setup.substitute("templates/common/common.sh", self._cfg)

        # directly copy /etc/hosts
        shutil.copyfile("templates/common/hosts", os.path.join(output_dir, "hosts"))

        if self._cfg["metrics"]:
            setup.append(_SETUP_METRICS)

        if self._cfg["local_firewall"]:
            util.awall.configure(self._cfg["interfaces"], self._cfg["roles"], setup, output_dir)

        interfaces = [util.interfaces.loopback(), util.interfaces.from_config(self._cfg["interfaces"])]
        util.file.write("interfaces", "\n".join(interfaces), output_dir)

        util.resolv.create_conf(self._cfg, output_dir)
        util.dhcpcd.create_conf(self._cfg, output_dir)
        _create_chrony_conf(self._cfg, output_dir)

        if self._cfg["is_vm"]:
            util.libvirt.write_vm_xml(self._cfg, output_dir)


def _setup_repos(cfg, setup):
    setup.append("echo \"Configuring APK repositories\"")
    setup.blank()

    repos = cfg["alpine_repositories"]

    # overwrite on first, append on subsequent
    setup.append(f"echo {repos[0]} > /etc/apk/repositories")

    for repo in repos[1:]:
        setup.append(f"echo {repo} >> /etc/apk/repositories")

    setup.blank()


def _apk_update(setup):
    setup.append("apk -q update")
    setup.blank()


def _create_chrony_conf(cfg, output_dir):
    buffer = []

    # use local NTP server if there is one defined
    if "local_ntp" in cfg:
        server = cfg["local_ntp"]
        buffer.append(f"server {server} iburst")
        buffer.append(f"initstepslew 10 {server}")
    else:
        for server in cfg["external_ntp"]:
            buffer.append(f"server {server} iburst")
        buffer.append("initstepslew 10 {}".format(" ".join(cfg["external_ntp"])))

    buffer.append("driftfile /var/lib/chrony/chrony.drift")
    buffer.append("rtcsync")

    util.file.write("chrony.conf", "\n".join(buffer), output_dir)


_SETUP_METRICS = """echo "Configuring Prometheus"
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
--collector.diskstats.device-exclude='^(ram|loop|fd|(h|s|v|xv)d[a-z]|nbd|sr|nvme\\\\d+n\\\\d+p)\\\\d+$' \\
--collector.filesystem.fs-types-exclude='^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tmpfs|tracefs|vfat)$'\\"" \\
> /etc/conf.d/node-exporter
"""
