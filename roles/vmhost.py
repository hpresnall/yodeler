"""Configuration & setup for the main KVM & Openvswitch Alpine host."""

import os
import shutil

from roles.role import Role

import config.interface as interface
import config.vlan as vlan

import util.file as file
import util.shell as shell
import util.libvirt as libvirt


class VmHost(Role):
    """VmHost defines the configuration needed to setup a KVM host using OpenVswitch."""

    def additional_packages(self):
        # packages for openvswitch, qemu, libvirt and alpine-make-vm-image
        return {"python3", "openvswitch", "qemu-system-x86_64", "qemu-img",
                "libvirt", "libvirt-daemon", "libvirt-qemu", "ovmf", "dbus", "polkit",
                "e2fsprogs", "rsync", "sfdisk", "git"}

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

            # iface for switch itself
            vswitch_interfaces.append(interface.for_port(vswitch_name, "vswitch"))

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

        self._cfg["interfaces"] = vswitch_interfaces + self._cfg["interfaces"]

    def additional_configuration(self):
        # do not support nested vms
        self._cfg["is_vm"] = False

        self.add_alias("kvm")

        # additional physical server config before running chroot during setup
        self._cfg["before_chroot"] = file.substitute("templates/vmhost/before_chroot.sh", self._cfg)

    def validate(self):
        pass

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        _setup_open_vswitch(self._cfg, setup,)
        _setup_libvirt(self._cfg, setup, output_dir)

        # call yodel.sh for each VM
        setup.comment("run yodel.sh for each VM for this site")
        setup.append("cd $SITE_DIR")
        setup.blank()

        setup.append("log -e \"\\nCreating VMs\\n\"")
        setup.blank()

        for _, host in self._cfg["hosts"].items():
            hostname = host["hostname"]

            if not host["is_vm"] or hostname == self._cfg["hostname"]:
                continue

            setup.append("log \"Creating VM for '" + hostname + "'\"")
            setup.append(hostname + "/yodel.sh")
            setup.append("log \"\"")
            setup.blank()

        # add uplinks _after_ setting up everything else, since uplinks can interfere with existing connectivity
        for vswitch in self._cfg["vswitches"].values():
            _create_vswitch_uplink(vswitch, setup)

        # directly copy patch for alpine-make-vm-image if it exists
        if os.path.isfile("templates/vmhost/patch"):
            shutil.copyfile("templates/vmhost/patch", os.path.join(output_dir, "patch"))


def _create_uplink_ports(vswitch: dict) -> list[dict]:
    uplinks = vswitch["uplinks"]
    vswitch_name = vswitch["name"]

    if not uplinks:
        return []
    elif len(uplinks) == 1:
        uplink = uplinks[0]
        return [interface.for_port(uplink, f"uplink for vswitch {vswitch_name}", vswitch_name, uplink)]
    else:
        ports = []
        for n, iface in enumerate(uplinks, start=1):
            ports.append(interface.for_port(
                iface, f"uplink {n} of {len(uplinks)} for vswitch {vswitch_name}", vswitch_name, iface))
        return ports


def _setup_open_vswitch(cfg, setup):
    setup.substitute("templates/vmhost/openvswitch.sh", cfg)

    # create Open vswitches for each definiation
    # add uplink ports with correct tagging where specified
    for vswitch in cfg["vswitches"].values():
        vswitch_name = vswitch["name"]

        setup.comment(f"setup vswitch '{vswitch_name}'")
        setup.append(f"ovs-vsctl add-br {vswitch_name}")
        setup.blank()

    # each host interface needs a port on the vswitch
    for iface in cfg["interfaces"]:
        if iface["type"] != "std":
            continue

        port = f"{cfg['hostname']}-{iface['vlan']['name']}"
        port = port[:15]  # Linux device names much be < 16 characters

        setup.comment(f"setup switch port for host interface on vswitch '{iface['vswitch']['name']}'")
        setup.append(
            f"ovs-vsctl add-port {iface['vswitch']['name']} {port} -- set interface {port} type=internal")

        if iface["vlan"]["id"] is not None:
            setup.append(f"ovs-vsctl set port {port} tag={iface['vlan']['id']} vlan_mode=access")

        setup.blank()


def _create_vswitch_uplink(vswitch, setup):
    # for each uplink, create a port on the vswitch
    uplinks = vswitch["uplinks"]

    if not uplinks:
        return []

    vswitch_name = vswitch["name"]

    if len(uplinks) > 1:
        # multiple uplink interfaces; create a bond named 'uplink'
        bond_ifaces = " ".join(uplinks)
        bond_name = f"{vswitch_name}-uplink"

        setup.comment("bonded uplink")
        setup.append(f"ovs-vsctl add-bond {vswitch_name} {bond_name} {bond_ifaces} lacp=active")

        uplink_name = bond_name  # use new uplink name for tagging, if needed
    else:
        uplink_name = next(iter(uplinks))

        setup.comment(f"uplink for vswitch '{vswitch_name}'")
        setup.append(f"ovs-vsctl add-port {vswitch_name} {uplink_name}")

    setup.blank()

    # tag the uplink port
    vlans_by_id = vswitch["vlans_by_id"].keys()
    if len(vlans_by_id) == 1:
        # single vlan with id => access port
        if None not in vlans_by_id:
            tag = list(vlans_by_id)[0]
            setup.append(f"ovs-vsctl set port {uplink_name} tag={tag} vlan_mode=access")
            setup.blank()
        # else no tagging needed
    elif len(vlans_by_id) > 1:  # multiple vlans => trunk port
        trunks = [str(vlan_id) for vlan_id in vlans_by_id if vlan_id != None]
        trunks = ",".join(trunks)

        # native or PVID vlan => native_untagged
        # see http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt
        vlan_mode = "native_untagged" if None in vlans_by_id else "trunk"
        setup.append(f"ovs-vsctl set port {uplink_name} trunks={trunks} vlan_mode={vlan_mode}")
        setup.blank()


def _setup_libvirt(cfg, setup, output_dir):
    setup.substitute("templates/vmhost/libvirt.sh", cfg)

    # for each vswitch, create an XML network definition
    for vswitch in cfg["vswitches"].values():
        libvirt.create_network(vswitch, output_dir)

        setup.append(f"virsh net-define $DIR/{vswitch['name']}.xml")
        setup.append(f"virsh net-start {vswitch['name']}")
        setup.append(f"virsh net-autostart {vswitch['name']}")
        setup.blank()
