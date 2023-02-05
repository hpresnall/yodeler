"""Configuration & setup for the main KVM & Openvswitch Alpine host."""

from roles.role import Role

import config.interface as interface
import config.vlan as vlan

import util.libvirt as libvirt


class VmHost(Role):
    """VmHost defines the configuration needed to setup a KVM host using OpenVswitch."""

    def __init__(self, cfg: dict):
        super().__init__("vmhost", cfg)

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
            # ifaces not net validated; manually look up vlan name
            iface_vswitch = self._cfg["vswitches"].get(iface.get("vswitch"))
            if not iface_vswitch:
                iface_vlan = "error"  # interface validation will error before exposing this name in config files
            else:
                iface_vlan = vlan.lookup(iface.get("vlan"), iface_vswitch)["name"]

            iface["name"] = f"{self._cfg['hostname']}-{iface_vlan}"
            iface["comment"] = "host interface"
            iface["parent"] = iface_vswitch["name"]

        self._cfg["interfaces"] = vswitch_interfaces + self._cfg["interfaces"]

    def additional_configuration(self):
        # do not support nested vms
        self._cfg["is_vm"] = False

        self.add_alias("vmhost")
        self.add_alias("kvm")

    def validate(self):
        pass

    def write_config(self, setup, output_dir):
        _setup_open_vswitch(self._cfg, setup,)
        _setup_libvirt(self._cfg, setup, output_dir)

        # call yodel.sh for each VM
        setup.comment("run yodel.sh for each VM for this site")
        setup.comment("site directory")
        setup.append("cd $DIR/..")  # site dir
        setup.blank()

        for _, host in self._cfg["hosts"].items():
            hostname = host["hostname"]

            if not host["is_vm"] or hostname == self._cfg["hostname"]:
                continue

            setup.append("echo \"Setting up VM '" + hostname + "'...\"")
            setup.append(hostname + "/yodel.sh")
            setup.blank()


def _create_uplink_ports(vswitch: dict) -> list[dict]:
    uplink = vswitch["uplink"]
    vswitch_name = vswitch["name"]

    if uplink is None:
        return []

    if isinstance(uplink, str):
        return [interface.for_port(uplink, f"uplink for vswitch {vswitch_name}", vswitch_name, uplink)]
    else:
        ports = []
        for n, iface in enumerate(uplink):
            ports.append(interface.for_port(
                iface, f"uplink {n+1} of {len(uplink)} for vswitch {vswitch_name}", vswitch_name, iface))
        return ports


def _setup_open_vswitch(cfg, setup):
    setup.substitute("templates/vmhost/openvswitch.sh", cfg)

    # create Open vswitches for each definiation
    # add uplink ports with correct tagging where specified
    for vswitch in cfg["vswitches"].values():
        vswitch_name = vswitch["name"]

        setup.comment(f"setup {vswitch_name} vswitch")
        setup.append(f"ovs-vsctl add-br {vswitch_name}")

        _create_vswitch_uplink(vswitch, setup)

    # each host interface needs a port on the vswitch
    for iface in cfg["interfaces"]:
        if iface["type"] != "std":
            continue

        port = f"{cfg['hostname']}-{iface['vlan']['name']}"

        setup.comment(f"setup switch port for host interface on vswitch {iface['vswitch']['name']}")
        setup.append(
            f"ovs-vsctl add-port {iface['vswitch']['name']} {port} -- set interface {port} type=internal")

        if iface["vlan"]["id"] is not None:
            setup.append(f"ovs-vsctl set port {port} tag={iface['vlan']['id']} vlan_mode=access")

        setup.blank()


def _create_vswitch_uplink(vswitch, setup):
    # for each uplink, create a port on the vswitch
    uplink = vswitch["uplink"]

    if uplink is None:
        return []

    setup.blank()
    vswitch_name = vswitch["name"]

    if not isinstance(uplink, str):
        # multiple uplink interfaces; create a bond named 'uplink'
        bond_ifaces = " ".join(uplink)
        bond_name = f"{vswitch_name}-uplink"

        setup.comment("bonded uplink")
        setup.append(f"ovs-vsctl add-bond {vswitch_name} {bond_name} {bond_ifaces} lacp=active")

        uplink = bond_name  # use new uplink name for tagging, if needed
    else:
        setup.comment("uplink")
        setup.append(f"ovs-vsctl add-port {vswitch_name} {uplink}")

    # tag the uplink port
    vlans_by_id = vswitch["vlans_by_id"].keys()
    if len(vlans_by_id) == 1:
        # single vlan with id => access port
        if None not in vlans_by_id:
            tag = list(vlans_by_id)[0]
            setup.append(f"ovs-vsctl set port {uplink} tag={tag} vlan_mode=access")
        # else no tagging needed
    elif len(vlans_by_id) > 1:  # multiple vlans => trunk port
        trunks = [str(vlan_id) for vlan_id in vlans_by_id if vlan_id != None]
        trunks = ",".join(trunks)

        # native or PVID vlan => native_untagged
        # see http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt
        vlan_mode = "native_untagged" if None in vlans_by_id else "trunk"
        setup.append(f"ovs-vsctl set port {uplink} trunks={trunks} vlan_mode={vlan_mode}")

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
