"""Configuration & setup for the router VM."""
import os.path
import os
import shutil

import util.file
import util.interfaces
import util.libvirt
import util.shell

import yodeler.vlan

from roles.role import Role


class Router(Role):
    """Router defines the configuration needed to setup a system that can route from the configured
     vlans to the internet"""

    def __init__(self):
        super().__init__("router")

    def additional_configuration(self, cfg):
        # router will use Shorewall & udhcpcd instead
        cfg["local_firewall"] = False
        cfg["remove_packages"].add("dhclient")

    def additional_packages(self):
        return {"shorewall", "shorewall6", "ipset", "radvd",
                "ulogd", "ulogd-json",
                "dhcpcd", "dhcrelay"}

    def create_scripts(self, cfg, output_dir):
        """Create the scripts and configuration files for the given host's configuration."""
        uplink = cfg.get("uplink")

        if uplink is None:
            raise KeyError("router must define an uplink")

        # uplink can be an existing vswitch or a physical iface on the host via macvtap
        if "vswitch" in uplink:
            yodeler.interface.validate_network(uplink, cfg["vswitches"])
            uplink_xml = _vswitch_uplink(cfg, uplink["vswitch"], uplink.get("vlan"))
        elif "macvtap" in uplink:
            uplink_xml = util.libvirt.macvtap_interface(cfg, uplink["macvtap"])
        else:
            raise KeyError(("invald uplink in router; "
                            "it must define a vswitch+vlan or a macvtap host interface"))

        uplink["comment"] = "internet uplink"
        uplink["name"] = "eth0"
        # IPv6 dhcp managed by udhcpd not ifupdown
        uplink["ipv6_dhcp"] = False

        yodeler.interface.validate_iface(uplink)
        interfaces = [util.interfaces.loopback(), util.interfaces.from_config([uplink])]

        interface_elements = [uplink_xml]
        shorewall_params = ["INTERNET=eth0"]
        shorewall_zones = ["fw\tfirewall\ninet\tipv4"]
        shorewall6_zones = ["fw\tfirewall\ninet\tipv6"]
        shorewall_interfaces = ["inet\t$INTERNET\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"]
        shorewall6_interfaces = ["inet\t$INTERNET\ttcpflags,dhcp,rpfilter,accept_ra=2"]
        shorewall_policy = []
        shorewall_snat = []

        iface_counter = 1
        untagged = False

        for vswitch in cfg["vswitches"].values():
            vswitch_name = vswitch["name"].upper()
            iface_name = f"eth{iface_counter}"
            vlan_interfaces = []

            for vlan in vswitch["vlans"]:
                if not vlan["routable"]:
                    continue

                shorewall_name = "$" + vswitch_name

                if vlan["id"] is None:
                    untagged = True
                else:
                    shorewall_name += f".{vlan['id']}"

                vlan_name = vlan["name"]
                vlan_interfaces.append(util.interfaces.for_vlan(vlan, iface_name))

                shorewall_zones.append(f"{vlan_name}\tipv4")
                shorewall6_zones.append(f"{vlan_name}\tipv6")

                shorewall_interfaces.append((f"{vlan_name}\t{shorewall_name}"
                                             "\ttcpflags,dhcp,nosmurfs,routefilter,logmartians"))
                shorewall6_interfaces.append((f"{vlan_name}\t{shorewall_name}"
                                              "\ttcpflags,dhcp,rpfilter,accept_ra=2"))

                all_access = False

                for access in vlan["access_vlans"]:
                    if access == "all":
                        all_access = True
                        shorewall_policy.append(f"# vlan {vlan_name} has full access to EVERYTHING")
                    else:
                        shorewall_policy.append(
                            f"# vlan {vlan_name} has full access to vlan {access}")
                    shorewall_policy.append(f"{vlan_name}\t{access}\tACCEPT")

                #  all acess => internet
                if not all_access and vlan["allow_internet"]:
                    shorewall_policy.append(f"# vlan {vlan_name} has full internet access")
                    shorewall_policy.append(f"{vlan_name}\tinet\tACCEPT")

                shorewall_snat.append(f"MASQUERADE\t{vlan['ipv4_subnet']}\t$INTERNET")

            if len(vlan_interfaces) > 0:
                comment = f"vlans on {vswitch['name']} vswitch"

                if untagged:  # parent interface already created; just output the comment
                    interfaces.append("# " + comment)
                else:  # create parent interface with the comment
                    interfaces.append(util.interfaces.port(iface_name, comment))

                interfaces.extend(vlan_interfaces)
                interface_elements.append(util.libvirt.router_interface(cfg['hostname'], vswitch))
                shorewall_params.append(vswitch_name + "=" + iface_name)

                iface_counter += 1
            # else no routable interfaces => do not create anything

        # re-number defined interfaces
        for iface in cfg["interfaces"]:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        # rewrite interfaces with uplink and vswitches / vlans first
        interfaces.append(util.interfaces.from_config(cfg["interfaces"]))
        util.file.write("interfaces", "\n".join(interfaces), output_dir)

        util.libvirt.update_interfaces(cfg['hostname'], interface_elements, output_dir)

        shorewall = os.path.join(output_dir, "shorewall")
        shorewall6 = os.path.join(output_dir, "shorewall6")

        os.mkdir(shorewall)
        os.mkdir(shorewall6)

        params = "\n".join(shorewall_params)
        util.file.write("params", params, shorewall)
        util.file.write("params", params, shorewall6)

        util.file.write("zones", "\n".join(shorewall_zones), shorewall)
        util.file.write("zones", "\n".join(shorewall6_zones), shorewall6)

        util.file.write("interfaces", "\n".join(shorewall_interfaces), shorewall)
        util.file.write("interfaces", "\n".join(shorewall6_interfaces), shorewall6)

        template = """
# drop everything coming in from the internet
inet all DROP    NFLOG({log})

# reject everything else
all all REJECT  NFLOG({log})
"""
        shorewall6_policy = list(shorewall_policy)
        shorewall_policy.append(template.format(log=4))
        shorewall6_policy.append(template.format(log=6))

        util.file.write("policy", "\n".join(shorewall_policy), shorewall)
        util.file.write("policy", "\n".join(shorewall6_policy), shorewall6)

        util.file.write("snat", "\n".join(shorewall_snat), shorewall)

        shutil.copyfile("templates/router/shorewall/rules", os.path.join(shorewall, "rules"))
        shutil.copyfile("templates/router/shorewall/rules6", os.path.join(shorewall6, "rules"))

        shell = util.shell.ShellScript("shorewall.sh")
        shell.substitute("templates/router/shorewall.sh", cfg)
        shell.write_file(output_dir)

        shutil.copy("templates/router/ipsets.save", output_dir)
        shutil.copy("templates/router/ulogd.conf", output_dir)
        shutil.copy("templates/router/ulogd", output_dir)

        return [shell.name]


def _vswitch_uplink(cfg, vswitch, vlan):
    if vswitch not in cfg["vswitches"]:
        raise KeyError(f"invalid router uplink; vswitch {vswitch} does not exist")

    vswitch = cfg["vswitches"][vswitch]

    try:
        vlan = yodeler.vlan.lookup(vlan, vswitch)
    except KeyError as err:
        msg = err.args[0]
        raise KeyError(f"invalid router uplink; {msg}")

    return util.libvirt.interface_from_config(cfg["hostname"], {"vswitch": vswitch, "vlan": vlan})
