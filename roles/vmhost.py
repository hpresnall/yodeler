"""Configuration & setup for the main KVM & Openvswitch Alpine server that runs other roles as VMs."""

import os
import string

from roles.role import Role

import config.interfaces as interfaces
import config.vlan as vlan

import util.file as file
import util.shell as shell
import util.libvirt as libvirt
import util.sysctl as sysctl


class VmHost(Role):
    """VmHost defines the configuration needed to setup a KVM host using OpenVswitch."""

    def additional_packages(self):
        # packages for openvswitch, qemu, libvirt and alpine-make-vm-image
        return {"python3", "openvswitch", "qemu-system-x86_64", "qemu-img",
                "libvirt", "libvirt-daemon", "libvirt-qemu", "ovmf", "dbus", "polkit",
                "virtiofsd", "e2fsprogs", "rsync", "sfdisk", "git", "xmlstarlet", "ethtool"}

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        # vm host needed if any other systems are vms
        for host_cfg in site_cfg["hosts"].values():
            if host_cfg["is_vm"]:
                return 1
        return 0

    def configure_interfaces(self):
        vswitch_interfaces = []

        for vswitch in self._cfg["vswitches"].values():
            vswitch_name = vswitch["name"]

            # create interfaces for iface for vswitch itself and its uplinks
            vswitch_interfaces.append(interfaces.for_port(vswitch_name, "vswitch", "vswitch"))
            vswitch_interfaces.extend(_create_uplink_ports(vswitch))

        # change original interface names to the open vswitch port name
        for iface in self._cfg["interfaces"]:
            # ifaces not yet validated; manually look up vlan name
            # vswitch and vlan could be objects if another role created the interface
            iface_vswitch = iface.get("vswitch")
            if not isinstance(iface_vswitch, dict):
                iface_vswitch = self._cfg["vswitches"].get(iface_vswitch)

            if iface_vswitch:
                iface_vlan = iface.get("vlan")
                if isinstance(iface_vlan, dict):
                    iface_vlan = iface_vlan["name"]
                else:
                    iface_vlan = vlan.lookup(iface_vlan, iface_vswitch)["name"]

                iface["parent"] = iface_vswitch["name"]
            else:
                # bubble up to host's interface.validate() call, which will fail with an invalid vswitch
                iface_vlan = "error"

            iface["name"] = f"{self._cfg['hostname']}-{iface_vlan}"
            iface["comment"] = "host interface"
            iface["subtype"] = "vmhost"

        self._cfg["interfaces"] = vswitch_interfaces + self._cfg["interfaces"]

    def additional_configuration(self):
        # do not support nested vms
        self._cfg["is_vm"] = False

        self.add_alias("kvm")

        if self._cfg["metrics"]:
            self._cfg["prometheus_collectors"].extend(["cgroups"])

        # additional physical server config before running chroot during setup
        self._cfg["before_chroot"].append(file.substitute("vmhost", "before_chroot.sh", self._cfg))
        self._cfg["after_chroot"].append(file.substitute("vmhost", "after_chroot.sh", self._cfg))

    def validate(self):
        # ensure no reused PCI addresses, uplink interfaces, disk images or disk devices
        uplinks = set()
        addresses = set()
        disks = set()

        # also track SRIOV virtual function counts by interface name
        vf_counts = {}

        for host in self._cfg["hosts"].values():
            if "uplink" in host:
                if "macvtap" in host["uplink"]:
                    uplink = host["uplink"]["macvtap"]

                    if uplink in uplinks:
                        raise ValueError(f"cannot reuse interface {uplink} for uplink in host {host['hostname']}")

                    uplinks.add(uplink)
                elif "passthrough" in host["uplink"]:
                    address = host["uplink"]["passthrough"]["pci_address"]
                    uplink = host["uplink"]["passthrough"]["name"]

                    if address in addresses:
                        raise ValueError(f"cannot reuse PCI address {address} for uplink in host {host['hostname']}")
                    if uplink in uplinks:
                        raise ValueError(f"cannot reuse interface {uplink} for uplink in host {host['hostname']}")

                    addresses.add(address)
                    uplinks.add(uplink)
                    if uplink in vf_counts:
                        vf_counts[uplink] += 1
                    else:
                        vf_counts[uplink] = 1

            for disk in host["disks"]:
                path = disk["path"]

                if path in disks:
                    raise ValueError(f"cannot reuse disk {path} in host {host['hostname']}")

                disks.add(path)

                if disk["type"] == "passthrough":
                    address = disk["pci_address"]
                    if address in addresses:
                        raise ValueError(f"cannot reuse PCI address {address} for disk in host {host['hostname']}")

                    addresses.add(address)

        self._cfg["vf_counts"] = vf_counts

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        _setup_open_vswitch(self._cfg, setup,)
        _setup_libvirt(self._cfg, setup, output_dir)

        local = False
        local_conf = ["# for vmhost interfaces, disable ipv6 on ipv4 only networks and enable ipv6 temporary addresses", ""]
        # run using the local service which runs _after_ the interfaces have been created by openvswitch
        # sysctl would run before the openvswitch port is created
        for iface in self._cfg["interfaces"]:
            if iface.get("subtype") != "vmhost":
                continue

            name = iface["name"]

            if iface["ipv6_disabled"]:
                local = True
                sysctl.add_disable_ipv6_to_script(local_conf, name)
                local_conf.append("")

            if iface["ipv6_tempaddr"]:
                local = True
                sysctl.add_tmpaddr_ipv6_to_script(local_conf, name)
                local_conf.append("")

        if local:
            file.write("ipv6.start", "\n".join(local_conf), output_dir)
            setup.comment("configure ipv6 on this host's network interfaces")
            setup.service("local")
            setup.append("install -o root -g root -m 750 $DIR/ipv6.start /etc/local.d")
            setup.blank()

        if not self._cfg["is_vm"]:
            setup.append("""# enable VT-d / IOMMU
if $(grep vendor_id /proc/cpuinfo | head -n 1 | grep AMD > /dev/null); then
  iommu="amd_iommu=pgtbl_v1"
else
  iommu="intel_iommu=on"
fi
sed -i -e \"s/quiet/${iommu} iommu=pt quiet/g\" /boot/grub/grub.cfg
""")

        # patch for alpine-make-vm-image if it exists
        if os.path.isfile("templates/vmhost/patch"):
            file.copy_template(self.name, "patch", output_dir)

        # libvirt hook scripts for network
        file.copy_template(self.name, "network_hook", output_dir)
        file.copy_template(self.name, "qemu_hook", output_dir)

        # libvirt hook script for daemon startup
        # create a code block for each SRIOV interface
        # config then requires setup for each virtual function
        vf_cfg_template = string.Template(file.read_template(self.name, "sriov.sh"))
        vf_cfg = []

        # virtual functions are variable so just substitue the variable name for the interface
        disable_vf_ipv6 = []
        sysctl.add_disable_ipv6_to_script(disable_vf_ipv6, "$vf", "    ")
        disable_vf_ipv6 = "\n".join(disable_vf_ipv6)

        for uplink, count in self._cfg["vf_counts"].items():
            disable_uplink_ipv6 = []
            sysctl.add_disable_ipv6_to_script(disable_uplink_ipv6, uplink, "  ")

            vf_cfg.append(vf_cfg_template.substitute({
                "UPLINK": uplink, "COUNT": count,
                "DISABLE_UPLINK_IPV6": "\n".join(disable_uplink_ipv6),
                "DISABLE_VF_IPV6": disable_vf_ipv6}))

        # combine all vf configs into a single substitution in the daemon script
        file.substitute_and_write(self.name, "daemon_hook", {"sriov": "\n".join(vf_cfg)}, output_dir)

        file.copy_template(self.name, "logrotate-openvswitch", output_dir)
        setup.append("rootinstall $DIR/logrotate-openvswitch /etc/logrotate.d/openvswitch")
        setup.blank()

        _create_site_build_image(self._cfg, setup, output_dir)

        # call yodel.sh for each VM
        setup.comment("run yodel.sh for each VM for this site")
        setup.append("cd $SITE_DIR")
        setup.append("log -e \"\\nCreating VMs\\n\"")

        for _, host in self._cfg["hosts"].items():
            hostname = host["hostname"]

            if not host["is_vm"] or hostname == self._cfg["hostname"]:
                continue

            setup.append(hostname + "/yodel.sh")
            setup.log("")

        setup.blank()
        setup.comment("add uplinks _after_ setting up everything else, since uplinks can interfere with existing connectivity")
        for vswitch in self._cfg["vswitches"].values():
            _create_vswitch_uplink(vswitch, setup)


def _create_uplink_ports(vswitch: dict) -> list[dict]:
    uplinks = vswitch["uplinks"]
    vswitch_name = vswitch["name"]

    if not uplinks:
        return []
    elif len(uplinks) == 1:
        uplink = uplinks[0]
        return [interfaces.for_port(uplink, f"uplink for vswitch {vswitch_name}", "uplink", parent=vswitch_name, uplink=uplink)]
    else:
        ports = []
        for n, iface in enumerate(uplinks, start=1):
            ports.append(interfaces.for_port(
                iface, f"uplink {n} of {len(uplinks)} for vswitch {vswitch_name}", "uplink", parent=vswitch_name, uplink=iface))
        return ports


def _setup_open_vswitch(cfg: dict, setup: shell.ShellScript):
    setup.substitute("vmhost", "openvswitch.sh", cfg)

    # create vswitches for each definition
    # add uplink ports with correct tagging where specified
    for vswitch in cfg["vswitches"].values():
        vswitch_name = vswitch["name"]

        setup.comment(f"vswitch '{vswitch_name}'")
        setup.append(f"ovs-vsctl add-br {vswitch_name}")
        setup.blank()

    # each interface on this host needs a port on the vswitch
    for iface in cfg["interfaces"]:
        if iface["type"] != "std":
            continue

        port = f"{cfg['hostname']}-{iface['vlan']['name']}"
        port = port[:15]  # Linux device names much be < 16 characters

        setup.comment(f"switch port for host interface on vswitch '{iface['vswitch']['name']}'")
        setup.append(
            f"ovs-vsctl add-port {iface['vswitch']['name']} {port} -- set interface {port} type=internal")

        if iface["vlan"]["id"] is not None:
            setup.append(f"ovs-vsctl set port {port} tag={iface['vlan']['id']} vlan_mode=access")

        setup.blank()


def _create_vswitch_uplink(vswitch: dict, setup: shell.ShellScript):
    # for each uplink, create a port on the vswitch
    uplinks = vswitch["uplinks"]

    if not uplinks:
        return []

    vswitch_name = vswitch["name"]

    if len(uplinks) > 1:
        # multiple uplink interfaces; create a bond named 'uplink'
        bond_ifaces = " ".join(uplinks)
        bond_name = f"{vswitch_name}-uplink"

        setup.comment(f"bonded uplink for vswitch '{vswitch_name}'")
        setup.append(
            f"ovs-vsctl add-bond {vswitch_name} {bond_name} {bond_ifaces} lacp=active bond_mode=balance-slb other-config:lacp-fallback-ab=true")

        uplink_name = bond_name  # use new uplink name for tagging, if needed
    else:
        uplink_name = uplinks[0]

        setup.comment(f"uplink for vswitch '{vswitch_name}'")
        setup.append(f"ovs-vsctl add-port {vswitch_name} {uplink_name}")

    # tag the uplink port
    vlans_by_id = vswitch["vlans_by_id"].keys()
    if len(vlans_by_id) == 1:
        # single vlan with id => access port
        if None not in vlans_by_id:
            tag = list(vlans_by_id)[0]
            setup.append(f"ovs-vsctl set port {uplink_name} tag={tag} vlan_mode=access")
        # else no tagging needed
    elif len(vlans_by_id) > 1:  # multiple vlans => trunk port
        trunks = [str(vlan_id) for vlan_id in vlans_by_id if vlan_id != None]
        trunks = ",".join(trunks)

        # native or PVID vlan => native_untagged
        # see http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt
        vlan_mode = "native_untagged" if None in vlans_by_id else "trunk"
        setup.append(f"ovs-vsctl set port {uplink_name} trunks={trunks} vlan_mode={vlan_mode}")

    setup.blank()


def _setup_libvirt(cfg: dict, setup: shell.ShellScript, output_dir: str):
    setup.substitute("vmhost", "libvirt.sh", cfg)

    # for each vswitch, create an XML network definition
    for vswitch in cfg["vswitches"].values():
        libvirt.create_network(vswitch, output_dir)

        setup.append(f"virsh net-define $DIR/{vswitch['name']}.xml")
        setup.append(f"virsh net-start {vswitch['name']}")
        setup.append(f"virsh net-autostart {vswitch['name']}")
        setup.blank()


def _create_site_build_image(cfg: dict, setup: shell.ShellScript, output_dir: str):
    # setup the site build image
    # also create a stand-along script for bootstrapping a new image if needed
    site_build = file.substitute("vmhost", "site_build.sh", cfg)
    setup.append(site_build)

    create_build = shell.ShellScript("create_build_img.sh")
    create_build.append_self_dir()
    create_build.append("""log () {
  echo $*
}
""")
    create_build.append(site_build)
    create_build.log("Build image mounted at $SITE_BUILD_IMG")
    create_build.write_file(output_dir)

    unmount_build = shell.ShellScript("unmount_build_img.sh")
    unmount_build.append_self_dir()
    unmount_build.append(f"SITE_BUILD_IMG=\"/media/{cfg['site_name']}_build\"")
    unmount_build.blank()
    unmount_build.append("umount $SITE_BUILD_IMG/tmp/apk_cache")
    unmount_build.append("umount $SITE_BUILD_IMG")
    unmount_build.blank()
    unmount_build.append("echo \"Unmounted $SITE_BUILD_IMG\"")
    unmount_build.write_file(output_dir)
