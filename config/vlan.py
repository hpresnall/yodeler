"""Handles parsing and validating vlan configuration from site YAML files."""
import logging
import ipaddress
import re

_logger = logging.getLogger(__name__)


def validate(domain, vswitch):
    """Validate all the vlans defined in the vswitch."""
    vswitch_name = vswitch["name"]

    vlans = vswitch.get("vlans")
    if (vlans is None) or (len(vlans) == 0):
        raise KeyError(f"no vlans defined for vswitch {vswitch_name}")
    if isinstance(vlans, str):
        raise KeyError(f"vlans cannot be a string for vswitch {vswitch_name}")

    # list of vlans in yaml => dicts of names & ids to vswitches
    vlans_by_id = vswitch["vlans_by_id"] = {}
    vlans_by_name = vswitch["vlans_by_name"] = {}

    for i, vlan in enumerate(vlans, start=1):
        # name is required and must be unique
        if not vlan.get("name") or (vlan["name"] == ""):
            raise KeyError(
                f"no name for vlan {i} in vswitch {vswitch_name}")

        vlan_name = vlan["name"]
        if vlan_name in vlans_by_name:
            raise KeyError(
                f"duplicate name {vlan_name} for vlan in vswitch {vswitch_name}")
        vlans_by_name[vlan_name] = vlan

        # vlan id must be unique
        # None is an allowed id and implies no vlan tagging
        vlan_id = vlan["id"] = vlan.get("id", None)

        if vlan_id in vlans_by_id:
            raise KeyError(
                f"duplicate id {vlan_id} for vlan {vlan_name} in vswitch {vswitch_name}")
        vlans_by_id[vlan_id] = vlan

        # add default values
        for key in DEFAULT_VLAN_CONFIG:
            if key not in vlan:
                vlan[key] = DEFAULT_VLAN_CONFIG[key]
        if "access_vlans" not in vlan:
            vlan["access_vlans"] = []  # optional list of other vlans this vlan can access _without_ firewall restrictions
        if "hosts" not in vlan:
            vlan["hosts"] = []  # optional list of hosts for DNS

        _validate_vlan_subnet(vswitch_name, vlan, "ipv4")
        _validate_vlan_subnet(vswitch_name, vlan, "ipv6")
        _validate_vlan_hosts(vswitch_name, vlan)

        # domain must be a subdomain of the top-level site
        if vlan["domain"] and (domain not in vlan["domain"]):
            raise KeyError(
                (f"vlan {vlan_name} domain {vlan['domain']} is not in top-level domain {domain} "
                 f"in vswitch {vswitch_name}"))

        ipv6_pd_network = vlan.get("ipv6_pd_network")

        if ipv6_pd_network is None:
            vlan["ipv6_pd_network"] = None
        else:
            if not isinstance(ipv6_pd_network, int):
                raise KeyError(f"ipv6_pd_network {ipv6_pd_network} must be an integer")
            vlan["ipv6_pd_network"] = ipv6_pd_network

    _configure_default_vlan(vswitch)
    _validate_access_vlans(vswitch)


def _validate_vlan_subnet(vswitch_name, vlan, ip_version):
    # ipv4 subnet is required
    # ipv6 subnet is optional; this does not preclude addresses from a prefix assignment
    subnet = vlan.get(ip_version + "_subnet")
    vlan_name = vlan["name"]

    if subnet is None:
        if ip_version == "ipv4":
            raise KeyError(
                f"no {ip_version}_subnet for vlan {vlan_name} in vswitch {vswitch_name}")
        if ip_version == "ipv6":
            vlan["ipv6_subnet"] = None
            return

    # remove the subnet if the vlan disables ipv6
    if ip_version == "ipv6" and vlan["ipv6_disable"]:
        vlan["ipv6_subnet"] = None
        return

    try:
        vlan[ip_version + "_subnet"] = subnet = ipaddress.ip_network(subnet)
    except Exception as exp:
        raise KeyError(
            f"invalid {ip_version}_subnet for vlan {vlan_name} in vswitch {vswitch_name}") from exp

    # default to DHCP range over all addresses except the router
    min_key = "dhcp_min_address_" + ip_version
    max_key = "dhcp_max_address_" + ip_version

    dhcp_min = vlan.get(min_key, DEFAULT_VLAN_CONFIG[min_key])
    dhcp_max = vlan.get(max_key, DEFAULT_VLAN_CONFIG[max_key])

    dhcp_min = subnet.network_address + dhcp_min
    dhcp_max = subnet.network_address + dhcp_max

    if dhcp_min not in subnet:
        raise KeyError((f"invalid {min_key} {dhcp_min} for vlan {vlan_name} "
                        f"in vswitch {vswitch_name}"))
    if dhcp_max not in subnet:
        raise KeyError((f"invalid {max_key} {dhcp_max} for vlan {vlan_name} "
                        f"in vswitch {vswitch_name}"))
    if dhcp_min > dhcp_max:
        raise KeyError((f"{min_key} > {max_key} for vlan {vlan_name} "
                        f"in vswitch {vswitch_name}"))


def _validate_vlan_hosts(vswitch_name, vlan):
    if len(vlan["hosts"]) == 0:
        return

    for i, host in enumerate(vlan["hosts"]):
        if "hostname" not in host:
            raise KeyError((f"no hostname for host {i} "
                            f"in vlan {vlan['name']} in vswitch {vswitch_name}"))

        _validate_ip_address("ipv4", i, vlan, vswitch_name)
        _validate_ip_address("ipv6", i, vlan, vswitch_name)

        if "mac_address" in host:
            if _VALID_MAC.match(host["mac_address"].upper()) is None:
                raise KeyError((f"invalid mac_address for host {i} "
                                f"in vlan {vlan['name']} in vswitch {vswitch_name}"))
        else:
            host["mac_address"] = None

        if "aliases" in host:
            if not isinstance(host["aliases"], list):
                raise KeyError((f"invalid aliases for host {i}; it must be an array "
                                f"in vlan {vlan['name']} in vswitch {vswitch_name}"))
        else:
            host["aliases"] = []


_VALID_MAC = re.compile("^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$")


def _validate_ip_address(ip_version, index, vlan, vswitch_name):
    key = ip_version + "_address"

    if key not in vlan["hosts"][index]:
        vlan["hosts"][index][key] = None
        return

    try:
        address = ipaddress.ip_address(vlan["hosts"][index][key])
    except Exception as exp:
        raise KeyError((f"invalid {ip_version}_address for host {index} "
                        f"in vlan {vlan['name']} for vswitch {vswitch_name}")) from exp

    if address not in vlan[ip_version + "_subnet"]:
        raise KeyError((f"invalid {ip_version}_address {address} for host{index}; "
                        f"it is not in vlan {vlan['name']}'s subnet "
                        f"for vswitch {vswitch_name}"))

    vlan["hosts"][index][key] = address

    if (ip_version == "ipv6") and (vlan["ipv6_subnet"] is None):
        _logger.warning(("ipv6_address %s for host %s"
                         " in vlan %s with ipv6 disabled in vswitch %s will be ignored"),
                        address, index, vlan['name'], vswitch_name)
        vlan["ipv6_address"] = None


def _configure_default_vlan(vswitch):
    # track which vlan is marked as the default
    default_vlan = None

    for vlan in vswitch["vlans"]:
        # only allow one default
        if "default" in vlan:
            if default_vlan is not None:
                raise KeyError(
                    f"multiple default vlans for vswitch {vswitch['name']}")
            default_vlan = vlan
        else:
            vlan["default"] = False

    if default_vlan is not None:
        vswitch["default_vlan"] = default_vlan
    elif len(vswitch['vlans_by_id']) == 1:  # one vlan; make it the default
        vlan = list(vswitch['vlans_by_id'].values())[0]
        vswitch["default_vlan"] = vlan
        vlan["default"] = True
    else:
        vswitch["default_vlan"] = None


def _validate_access_vlans(vswitch):
    for vlan in vswitch["vlans"]:
        vlan_name = vlan["name"]
        access_vlans = vlan["access_vlans"]

        if not isinstance(access_vlans, list):
            if isinstance(access_vlans, str):
                access_vlans = [access_vlans]
            else:
                raise KeyError(
                    f"non-array access_vlans in vlan {vlan_name} for vswitch {vswitch['name']}")

        vlan["access_vlans"] = []

        # set() to make unique
        for vlan_id in set(access_vlans):
            if vlan_id == "all":
                vlan["access_vlans"] = ["all"]
                break

            try:
                access = lookup(vlan_id, vswitch)
                vlan["access_vlans"].append(access["name"])
            except KeyError as err:
                msg = err.args[0]
                raise KeyError(f"access_vlan {msg}") from err


def lookup(vlan_id, vswitch):
    """Get the vlan object from the given vswitch. vlan_id can be either an id or a name."""
    if isinstance(vlan_id, str):
        lookup_dict = vswitch["vlans_by_name"]
    else:
        lookup_dict = vswitch["vlans_by_id"]  # also handles None

    # no vlan set; could be a PVID vlan on the vswitch
    # if not, use the default vlan
    vlan = lookup_dict.get(vlan_id)
    if vlan_id is None:
        if vlan is None:
            vlan = vswitch["default_vlan"]

        if vlan is None:
            raise KeyError(
                f"vlan id must be specified when vswitch {vswitch['name']} has no default vlan")
    else:
        if vlan is None:
            raise KeyError(
                f"invalid vlan {vlan_id}; not defined in vswitch {vswitch['name']}")

    return vlan


# accessible for testing
DEFAULT_VLAN_CONFIG = {
    "routable": True,  # vlan will have an interface assigned on the router
    "domain": "",
    "ipv6_disable": False,
    "allow_dhcp": True,  # DHCP server will be configured
    "allow_internet": False,  # firewall will restrict outbound internet access
    # do not allow internet access when firewall is stopped
    "allow_access_stopped_firewall": False,
    "allow_dns_update": False,  # do not allow this subnet to make DDNS updates
    "dhcp_min_address_ipv4": 2,
    "dhcp_max_address_ipv4": 252,
    "dhcp_min_address_ipv6": 2,
    "dhcp_max_address_ipv6": 0xffff,
}
