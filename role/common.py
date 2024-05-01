"""Common configuration & setup for all Alpine servers."""
from role.roles import Role

import util.file as file

import script.awall as awall
import script.chrony as chrony
import script.disks as disks
import script.dhcpcd as dhcpcd
import script.interfaces as interfaces
import script.libvirt as libvirt
import script.metrics as metrics
import script.resolv as resolv
import script.shell as shell
import script.sysctl as sysctl


class Common(Role):
    """Common setup required for all systems. This role _must_ be run before any other setup."""

    def additional_packages(self):
        # use dhcpcd for dhcp since it can also handle prefix delegation for routers
        # use better ifupdown-ng  and the Linux ip command, instead of Busybox's built-ins
        packages = {"e2fsprogs", "acpi", "doas", "openssh", "chrony", "curl",
                    "logrotate", "awall", "dhcpcd", "ifupdown-ng", "iproute2"}

        for iface in self._cfg["interfaces"]:
            if iface["name"].startswith("wlan"):
                packages.add("ifupdown-ng-wifi")
                break

        # needed for checking existing partitions and getting UUIDs
        for disk in self._cfg["disks"]:
            if disk["type"] != "img":
                packages.add("lsblk")

        # remove iptables if there is no local firewall
        if not self._cfg["local_firewall"]:
            self._cfg["remove_packages"].add("iptables")
            self._cfg["packages"].discard("awall")

        # add utilities for physical servers
        if not self._cfg["is_vm"]:
            packages.update(["util-linux", "pciutils", "dmidecode", "cpufrequtils", "nvme-cli", "smartmontools",
                             "lm-sensors", "ethtool"])

        return packages

    def additional_configuration(self):
        self._cfg["fqdn"] = ""
        if self._cfg["primary_domain"]:
            self._cfg["fqdn"] = self._cfg["hostname"] + '.' + self._cfg["primary_domain"]

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

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        # write all packages to a file; usage depends on vm or physical server
        file.write("packages", " ".join(self._cfg["packages"]), output_dir)

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
            setup.log("Installing required packages")
            setup.comment("this server could be using a repo with newer package versions")
            setup.comment("upgrade any packages added by alpine installer, then install the required packages")
            setup.append("apk -q --no-progress upgrade")
            setup.append("apk -q --no-progress add $(cat $DIR/packages)")
            setup.blank()

        if (self._cfg["remove_packages"]):
            setup.log("Removing unneeded packages")
            setup.append("apk -q del " + " ".join(self._cfg["remove_packages"]))
            setup.blank()

        setup.substitute(self.name, "common.sh", self._cfg)

        # directly copy /etc/hosts
        file.copy_template(self.name, "hosts", output_dir)

        interfaces.from_config(self._cfg, output_dir)
        interfaces.rename_interfaces(self._cfg["rename_interfaces"], setup, output_dir, self._cfg["hostname"])

        sysctl.disable_ipv6(self._cfg, setup, output_dir)

        awall.configure(self._cfg, setup, output_dir)
        metrics.configure(self._cfg, setup, output_dir)

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
                file.write("resolv.conf.head", resolv.create_conf(self._cfg), output_dir)
            # else dhcp4 and dhcp6 will provide all needed resolve.conf info
            dhcpcd.create_conf(self._cfg, output_dir)
            setup.service("dhcpcd", "boot")
            setup.blank()
            sysctl.enable_temp_addresses(self._cfg, setup, output_dir)
        elif need_dhcp4:
            # no ipv6; dhcp4 will provide all needed resolve.conf info
            dhcpcd.create_conf(self._cfg, output_dir)
            setup.service("dhcpcd", "boot")
            setup.blank()
        else:
            # static ipv4 and no ipv6 => static resolve.conf and no dhcpcd needed
            file.write("resolv.conf", resolv.create_conf(self._cfg), output_dir)

        chrony.create_conf(self._cfg, output_dir)

        disks.from_config(self._cfg, setup)

        if self._cfg["is_vm"]:
            libvirt.write_vm_xml(self._cfg, output_dir)

            if self._cfg["host_backup"]:
                setup.comment("mount /backup at boot")
                setup.append("echo -e \"backup\\t/backup\\tvirtiofs\\trw,relatime\\t0\\t0\" >> /etc/fstab")


def _setup_repos(cfg: dict, setup: shell.ShellScript):
    setup.log("Setting up APK repositories")
    setup.blank()

    repos = list(cfg["alpine_repositories"])

    # overwrite on first, append on subsequent
    setup.append(f"echo {repos[0]} > /etc/apk/repositories")

    for repo in repos[1:]:
        setup.append(f"echo {repo} >> /etc/apk/repositories")

    setup.blank()
