"""Common configuration & setup for all Alpine hosts."""
import util.awall
import util.disks
import util.dhcpcd
import util.file
import util.interfaces
import util.libvirt
import util.parse
import util.resolv
import util.shell
import util.sysctl

from roles.role import Role
import roles.ntp


class Common(Role):
    """Common setup required for all systems. This role _must_ be run before any other setup."""

    def additional_packages(self):
        # use dhcpcd for dhcp since it can also handle prefix delegation for routers
        # use better ifupdown-ng  and the Linux ip command, instead of Busybox's built-ins
        packages = {"e2fsprogs", "acpi", "doas", "openssh", "chrony",
                    "logrotate", "awall", "dhcpcd", "ifupdown-ng", "iproute2"}

        for iface in self._cfg["interfaces"]:
            if iface["name"].startswith("wlan"):
                packages.add("ifupdown-ng-wifi")
                break

        # needed for checking existing partitions and getting UUIDs
        for disk in self._cfg["disks"]:
            if disk["type"] != "img":
                packages.add("lsblk")

        return packages

    def additional_configuration(self):
        self._cfg["fqdn"] = ""
        if self._cfg["primary_domain"]:
            self._cfg["fqdn"] = self._cfg["hostname"] + '.' + self._cfg["primary_domain"]

        if not self._cfg["is_vm"] and self._cfg["metrics"]:
            # additional metrics for physical hosts
            self._cfg["prometheus_collectors"].extend(["edac", "hwmon", "nvme", "thermal_zone", "cpufreq"])

    def validate(self):
        # ensure each vlan is only used once
        # do not allow multiple interfaces with routable vlans on the same switch
        vswitches_used = set()
        vlans_used = set()

        for iface in self._cfg["interfaces"]:
            if iface["type"] != "std":
                continue

            vlan = iface["vlan"]
            vlan_name = vlan["name"]

            if vlan_name in vlans_used:
                raise ValueError(f"host '{self._cfg['hostname']} defines multiple interfaces on vlan '{vlan_name}'")
            vlans_used.add(vlan_name)

            vswitch_name = iface["vswitch"]["name"]

            if vlan["routable"] and (vswitch_name in vswitches_used):
                raise ValueError(
                    f"host '{self._cfg['hostname']} defines interfaces on multiple routable vlans for switch '{vswitch_name}'")

            vswitches_used.add(vswitch_name)

    def write_config(self, setup: util.shell.ShellScript, output_dir: str):
        # write all packages to a file; usage depends on vm or physical server
        util.file.write("packages", " ".join(self._cfg["packages"]), output_dir)

        if self._cfg["is_vm"]:
            # VMs will use host's configured repositories & APK cache
            # packages will be installed as part of image creation

            # VMs are setup without USB, so remove the library
            self._cfg["remove_packages"].add("libusb")
        else:
            # for physical servers, add packages manually
            _setup_repos(self._cfg, setup)
            setup.append("apk -q update")
            setup.append("apk cache sync")
            setup.blank()
            setup.append("log \"Installing required packages\"")
            setup.comment("this server could be using a repo with newer package versions")
            setup.comment("upgrade any packages added by alpine installer, then install the required packages")
            setup.append("apk -q --no-progress upgrade")
            setup.append("apk -q --no-progress add $(cat $DIR/packages)")
            setup.blank()

        if (self._cfg["remove_packages"]):
            setup.append("log \"Removing unneeded packages\"")
            setup.append("apk -q del " + " ".join(self._cfg["remove_packages"]))
            setup.blank()

        setup.substitute("templates/common/common.sh", self._cfg)

        # directly copy /etc/hosts
        util.file.copy_template(self.name, "hosts", output_dir)

        if self._cfg["metrics"]:
            setup.append("log \"Configuring Prometheus\"")
            setup.service("node-exporter")
            # awful formatting; put each prometheus arg on a separate line ending with '\'
            # then, the whole command needs to be echoed to a file as a quoted param
            node_exporter_cmd = " \\\n".join(_PROMETHEUS_ARGS) + " "  \
                + " \\\n".join("--collector.%s" % c for c in self._cfg["prometheus_collectors"])
            setup.append("echo \"ARGS=\\\"" + node_exporter_cmd + "\\\"\" > /etc/conf.d/node-exporter")
            setup.blank()

        if self._cfg["local_firewall"]:
            util.awall.configure(self._cfg["interfaces"], self._cfg["roles"], setup, output_dir)

        util.file.write("interfaces", util.interfaces.from_config(self._cfg), output_dir)

        util.sysctl.disable_ipv6(self._cfg, setup, output_dir)

        if "rename_interfaces" in self._cfg:
            # create init script & add it to boot
            rename_cmds = []
            for rename in self._cfg["rename_interfaces"]:
                rename_cmds.append(f"  rename_iface {rename['mac_address']} {rename['name']}")

            util.file.write("rename-eth", util.file.substitute(
                "templates/common/rename-eth", {"rename_cmds": "\n".join(rename_cmds)}), output_dir)

            setup.comment("rename ethernet devices at boot")
            setup.append("install -m 755 $DIR/rename-eth /etc/init.d")
            setup.service("rename-eth", "sysinit")
            setup.blank()

        # create resolve.conf as needed, based on dhcp and ipv6 configuration
        # this also determines the need for dhcpcd
        need_ipv6 = False
        need_dhcp4 = False

        for iface in self._cfg["interfaces"]:
            # ignore dhcp on the router so it has external and internal resolve.conf info
            if (iface["ipv4_address"] == "dhcp") and (iface["type"] != "uplink"):
                need_dhcp4 = True
            if not iface["ipv6_disabled"]:
                need_ipv6 = True

        if need_ipv6:
            # dhcp6 or router advertisements will provide ipv6 dns config
            if not need_dhcp4:
                # do not let ipv6 overwrite static ipv4 dns config
                util.file.write("resolv.conf.head", util.resolv.create_conf(self._cfg), output_dir)
            # else dhcp4 and dhcp6 will provide all needed resolve.conf info
            util.dhcpcd.create_conf(self._cfg, output_dir)
            setup.service("dhcpcd", "boot")
            setup.blank()
            util.sysctl.enable_temp_addresses(self._cfg, setup, output_dir)
        elif need_dhcp4:
            # no ipv6; dhcp4 will provide all needed resolve.conf info
            util.dhcpcd.create_conf(self._cfg, output_dir)
            setup.service("dhcpcd", "boot")
            setup.blank()
        else:
            # static ipv4 and no ipv6 => static resolve.conf and no dhcpcd needed
            util.file.write("resolv.conf", util.resolv.create_conf(self._cfg), output_dir)

        roles.ntp.create_chrony_conf(self._cfg, output_dir)

        util.disks.from_config(self._cfg, setup)

        if self._cfg["is_vm"]:
            util.libvirt.write_vm_xml(self._cfg, output_dir)

            if self._cfg["host_backup"]:
                setup.comment("mount /backup at boot")
                setup.append("echo -e \"backup\\t/backup\\tvirtiofs\\trw,relatime\\t0\\t0\" >> /etc/fstab")


def _setup_repos(cfg: dict, setup: util.shell.ShellScript):
    setup.append("log \"Setting up APK repositories\"")
    setup.blank()

    repos = list(cfg["alpine_repositories"])

    # overwrite on first, append on subsequent
    setup.append(f"echo {repos[0]} > /etc/apk/repositories")

    for repo in repos[1:]:
        setup.append(f"echo {repo} >> /etc/apk/repositories")

    setup.blank()


# ignore all ram, loop, floppy disks and all _partitions_
# ignore all non-file systems
_PROMETHEUS_ARGS = [
    "--log.level=warn",
    "--collector.diskstats.device-exclude='^(ram|loop|fd[a-z]|((h|s|v|xv)d[a-z]|nbd|sr|nvme\\\\d+n\\\\d+p))\\\\d+$'",
    "--collector.filesystem.fs-types-exclude='^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tmpfs|tracefs)$'",
    "--collector.disable-defaults"
]

# for storage zfs
