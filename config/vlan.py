"""Handles parsing and validating vlan configuration from site YAML files."""
import logging
import ipaddress
import re

import util.parse as parse

import roles.role

_logger = logging.getLogger(__name__)


def validate(domain: str, vswitch: dict, other_vswitch_vlans: set):
    """Validate all the vlans defined in the vswitch."""
    vswitch_name = vswitch["name"]

    vlans = parse.non_empty_list("vlans", vswitch.get("vlans"))

    # list of vlans in yaml => dicts of names & ids to vswitches
    vlans_by_id = vswitch["vlans_by_id"] = {}
    vlans_by_name = vswitch["vlans_by_name"] = {}

    for i, vlan in enumerate(vlans, start=1):
        cfg_name = f"vswitch['{vswitch_name}'].vlan[{i}]"
        parse.non_empty_dict(cfg_name, vlan)

        # name is required and must be unique; lowercase for consistency
        vlan_name = parse.non_empty_string("name", vlan, cfg_name).lower()
        vlan["name"] = vlan_name

        if vlan_name in vlans_by_name:
            raise KeyError(f"duplicate name '{vlan_name}' for {cfg_name}")
        if vlan_name in other_vswitch_vlans:
            raise KeyError(f"duplicate name '{vlan_name}' for {cfg_name}")

        other_vswitch_vlans.add(vlan_name)
        vlans_by_name[vlan_name] = vlan

        cfg_name = f"vswitch['{vswitch_name}'].vlan['{vlan['name']}']"

        # vlan id must be unique
        # None is an allowed id and implies no vlan tagging
        vlan_id = vlan.setdefault("id", None)

        if vlan_id is not None:
            if not isinstance(vlan_id, int):
                raise KeyError(f"non-integer id '{vlan_id}' for {cfg_name}")
            if (vlan_id < 1) or (vlan_id > 4094):
                raise KeyError(f"invalid id '{vlan_id}' for {cfg_name}")

        if vlan_id in vlans_by_id:
            raise KeyError(f"duplicate id '{vlan_id}' for {cfg_name}")

        vlans_by_id[vlan_id] = vlan

        parse.configure_defaults(cfg_name, DEFAULT_VLAN_CONFIG, _DEFAULT_VLAN_CONFIG_TYPES, vlan)

        # optional list of other vlans this vlan can access _without_ firewall restrictions
        # allows special value 'all' to indicate access to every vlan on the vswitch
        vlan["access_vlans"] = parse.read_string_list_plurals({"access_vlan", "access_vlans"}, vlan, cfg_name)
        vlan.pop("access_vlan", None)

        _validate_vlan_subnet(vswitch_name, vlan, "ipv4")
        _validate_vlan_subnet(vswitch_name, vlan, "ipv6")
        _validate_vlan_dhcp_reservations(vswitch_name, vlan)

        # domain must be a subdomain of the top-level site
        if vlan["domain"] and ((domain not in vlan["domain"]) or (domain == vlan["domain"])):
            raise KeyError(
                f"vlan '{vlan_name}' domain '{vlan['domain']}' is not in top-level domain '{domain}' for vswitch '{vswitch_name}'")

        ipv6_pd_network = vlan.setdefault("ipv6_pd_network", None)
        if ipv6_pd_network is not None:
            if not isinstance(ipv6_pd_network, int):
                raise KeyError(f"ipv6_pd_network '{ipv6_pd_network}' must be an integer")
            if ipv6_pd_network < 1:
                raise KeyError(f"ipv6_pd_network '{ipv6_pd_network}' must be greater than 0")

    _configure_default_vlan(vswitch)
    _validate_access_vlans(vswitch)


def _validate_vlan_subnet(vswitch_name: str, vlan: dict, ip_version: str):
    # ipv4 subnet is required
    # ipv6 subnet is optional; this does not preclude addresses from a prefix assignment
    subnet = vlan.get(ip_version + "_subnet")
    vlan_name = vlan["name"]
    cfg_name = f"vswitch['{vswitch_name}'].vlan['{vlan['name']}']"

    if subnet is None:
        if ip_version == "ipv4":
            raise KeyError(f"no {ip_version}_subnet for {cfg_name}")
        if ip_version == "ipv6":
            vlan["ipv6_subnet"] = None
            return
    subnet = str(subnet)

    # remove the subnet if the vlan disables ipv6
    if (ip_version == "ipv6") and (vlan["ipv6_disabled"]):
        vlan["ipv6_subnet"] = None
        return

    try:
        vlan[ip_version + "_subnet"] = subnet = ipaddress.ip_network(subnet)
    except ValueError as ve:
        raise ValueError(f"invalid {ip_version}_subnet for {cfg_name}") from ve

    if (ip_version == "ipv6") and (subnet.prefixlen> 64):
        raise ValueError(f"invalid {ip_version}_subnet for {cfg_name}; the prefix length cannot be greater than 64")

    # default to DHCP range over all addresses except the router
    min_key = "dhcp_min_address_" + ip_version
    max_key = "dhcp_max_address_" + ip_version

    dhcp_min = vlan.get(min_key, DEFAULT_VLAN_CONFIG[min_key])
    dhcp_max = vlan.get(max_key, DEFAULT_VLAN_CONFIG[max_key])

    dhcp_min = subnet.network_address + dhcp_min
    dhcp_max = subnet.network_address + dhcp_max

    if dhcp_min not in subnet:
        raise KeyError(f"invalid {min_key} '{dhcp_min}' for vlan '{vlan_name}' for vswitch '{vswitch_name}'")
    if dhcp_max not in subnet:
        raise KeyError(f"invalid {max_key} '{dhcp_max}' for vlan '{vlan_name}' for vswitch '{vswitch_name}'")
    if dhcp_min > dhcp_max:
        raise KeyError(f"{min_key} > {max_key} for vlan '{vlan_name}' for vswitch '{vswitch_name}'")


_VALID_MAC = re.compile("^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$")


def _validate_vlan_dhcp_reservations(vswitch_name: str, vlan: dict):
    reservations = vlan.setdefault("dhcp_reservations", [])
    cfg_name = f"vswitch['{vswitch_name}'].vlan['{vlan['name']}']"

    if not isinstance(reservations, list):
        raise KeyError(f"dhcp_reservations in {cfg_name} must be an array")

    known_aliases = set()
    role_names = roles.role.names()

    for i, res in enumerate(reservations, start=1):
        location = f"{cfg_name}.dhcp_reservations[{i}]"
        parse.non_empty_dict(location, res)

        # hostname & mac address required; ip addresses are not
        hostname = parse.non_empty_string("hostname", res, location).lower()

        if hostname in known_aliases:
            raise ValueError(f"duplicate hostname or alias '{hostname}' in {cfg_name}")
        known_aliases.add(hostname)

        # cannot check for duplicate cfg[hosts] / aliases here since hosts have not yet been defined
        res["hostname"] = hostname

        _validate_ip_address("ipv4", i-1, vlan, vswitch_name, location)
        _validate_ip_address("ipv6", i-1, vlan, vswitch_name, location)

        if "mac_address" in res:
            mac = res["mac_address"]
            if not isinstance(mac, str):
                raise KeyError(f"invalid mac_address for {location}")
            if _VALID_MAC.match(mac.upper()) is None:
                raise KeyError(f"invalid mac_address for {location}")
        else:
            raise KeyError(f"no mac_address for {location}")
        # mac address case is up to the users of the reservations

        aliases = parse.read_string_list_plurals({"alias", "aliases"}, res, location)
        res.pop("alias", None)

        res["aliases"] = set()

        for alias in aliases:
            alias = alias.lower()
            if alias == hostname:
                continue
            if alias in known_aliases:
                raise ValueError(f"duplicate hostname or alias '{hostname}' in {cfg_name}")
            known_aliases.add(alias)
            res["aliases"].add(alias)

    if not known_aliases.isdisjoint(role_names):
        raise ValueError(
            f"{cfg_name}' contains DHCP reservations that conflict with a role name; {known_aliases.intersection(role_names)}")

    vlan["known_aliases"] = known_aliases  # track for easier ducplicate checking of hosts/aliases
    _logger.debug("%s known_aliases=%s", cfg_name, known_aliases)


def _validate_ip_address(ip_version: str, index: int, vlan: dict, vswitch_name: str, location: str):
    key = ip_version + "_address"

    if key not in vlan["dhcp_reservations"][index]:
        vlan["dhcp_reservations"][index][key] = None
        return

    try:
        address = ipaddress.ip_address(vlan["dhcp_reservations"][index][key])
    except ValueError as ve:
        raise KeyError(f"invalid {ip_version}_address for {location}") from ve

    if (ip_version == "ipv6") and (vlan["ipv6_subnet"] is None):
        _logger.warning("ipv6_address %s for %s with no ipv6_subnet will be ignored", address, location)
        return

    if address not in vlan[ip_version + "_subnet"]:
        raise KeyError(f"invalid {ip_version}_address {address} for {location}; it is not in the vlan's subnet")

    vlan["dhcp_reservations"][index][key] = address


def _configure_default_vlan(vswitch: dict):
    # track which vlan is marked as the default
    default_vlan = None

    for vlan in vswitch["vlans"]:
        # only allow one default
        if "default" in vlan:
            if default_vlan is not None:
                raise KeyError(f"multiple default vlans for vswitch '{vswitch['name']}'")
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


def _validate_access_vlans(vswitch: dict):
    for vlan in vswitch["vlans"]:
        access_vlans = []

        for vlan_id in vlan["access_vlans"]:
            if vlan_id == "all":  # if any value is all, only value is all
                access_vlans = ["all"]
                break
            try:
                # accept name or number; store name
                access_vlan = lookup(vlan_id, vswitch)
                access_vlans.append(access_vlan["name"])
            except KeyError as ke:
                msg = ke.args[0]
                raise KeyError(f"invalid access_vlan in vlan '{vlan['name']}': {msg}") from ke

        vlan["access_vlans"] = access_vlans


def lookup(vlan_id: str | int | None, vswitch: dict):
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
            raise KeyError(f"vlan id must be specified when vswitch '{vswitch['name']}' has no default vlan")
    else:
        if vlan is None:
            raise KeyError(f"invalid vlan '{vlan_id}'; not defined in vswitch '{vswitch['name']}'")

    return vlan


# accessible for testing
DEFAULT_VLAN_CONFIG = {
    "routable": True,  # vlan will have an interface assigned on the router
    "domain": "",
    "ipv6_disabled": False,
    "dhcp4_enabled": True,  # DHCP server will be configured
    "allow_internet": False,  # firewall will restrict outbound internet access
    # do not allow internet access when firewall is stopped
    "allow_access_stopped_firewall": False,
    "allow_dns_update": False,  # do not allow this subnet to make DDNS updates
    "dhcp_min_address_ipv4": 16,
    "dhcp_max_address_ipv4": 252,
    # by default, the managed flag is set to false in router advertisements; DHCP6 will be used for information only
    # set to false and optionally set dhcp_min_address_ipv6 & dhcp_max_address_ipv6 to have DHCP6 provided addresses
    "dhcp6_managed": False,
    "dhcp_min_address_ipv6": 16,
    "dhcp_max_address_ipv6": 0xffff
}

_DEFAULT_VLAN_CONFIG_TYPES = {
    "name": str,
    "id": int,
    "routable": bool,
    "domain": str,
    "ipv6_disabled": bool,
    "dhcp4_enabled": bool,
    "allow_internet": bool,
    "allow_access_stopped_firewall": bool,
    "allow_dns_update": bool,
    "dhcp_min_address_ipv4": int,
    "dhcp_max_address_ipv4": int,
    "dhcp6_managed": bool,
    "dhcp_min_address_ipv6": int,
    "dhcp_max_address_ipv6": int
}
