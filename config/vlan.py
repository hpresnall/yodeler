"""Handles parsing and validating vlan configuration from site YAML files."""
import logging
import ipaddress

import util.dns as dns
import util.parse as parse

import role.roles as roles

_logger = logging.getLogger(__name__)


def validate(domain: str, vswitch: dict, other_vswitch_vlans: set, other_ipv4_subnets: set, other_ipv6_subnets: set):
    """Validate all the vlans defined in the vswitch."""
    vswitch_name = vswitch["name"]

    vlans = parse.non_empty_list("vlans", vswitch.get("vlans"))

    # list of vlans in yaml => dicts of names & ids to vswitches
    vlans_by_id = vswitch["vlans_by_id"] = {}
    vlans_by_name = vswitch["vlans_by_name"] = {}

    # possibly delegate an IPv6 prefix to each vlan
    # start at 1 => do not delegate the 0 network
    # prefix for each vlan is in the order they are defined unless vlan['ipv6_pd_network'] is set
    # each vswitch will need a _separate_ prefix delegation
    ipv6_pd_networks = set()
    ipv6_pd_network_count = 1

    for i, vlan in enumerate(vlans, start=1):
        location = f"vswitch['{vswitch_name}'].vlan[{i}]"
        parse.non_empty_dict(location, vlan)

        # name is required and must be unique; lowercase for consistency
        vlan_name = parse.non_empty_string("name", vlan, location).lower()
        vlan["name"] = vlan_name

        if vlan_name in vlans_by_name:
            raise ValueError(f"{location} duplicate name '{vlan_name}'")
        if vlan_name in other_vswitch_vlans:
            raise ValueError(f"{location} duplicate name '{vlan_name}'")

        other_vswitch_vlans.add(vlan_name)
        vlans_by_name[vlan_name] = vlan

        location = f"vswitch['{vswitch_name}'].vlan['{vlan['name']}']"

        # vlan id must be unique
        # None is an allowed id and implies no vlan tagging
        vlan_id = vlan.setdefault("id", None)

        if vlan_id is not None:
            if not isinstance(vlan_id, int):
                raise ValueError(f"{location} non-integer id '{vlan_id}'")
            if (vlan_id < 1) or (vlan_id > 4094):
                raise ValueError(f"{location} invalid id '{vlan_id}'")

        if vlan_id in vlans_by_id:
            raise ValueError(f"{location} duplicate id '{vlan_id}'")

        vlans_by_id[vlan_id] = vlan

        parse.configure_defaults(location, DEFAULT_VLAN_CONFIG, _DEFAULT_VLAN_CONFIG_TYPES, vlan)

        vlan["known_aliases"] = set()  # track for easier ducplicate checking of hosts/aliases

        _validate_subnet(vswitch_name, vlan, "ipv4", other_ipv4_subnets)
        _validate_subnet(vswitch_name, vlan, "ipv6", other_ipv6_subnets)
        _validate_dhcp_reservations(vswitch_name, vlan)
        _validate_static_hosts(vswitch_name, vlan)
        _validate_ipv6_pd_network(vlan, ipv6_pd_networks, ipv6_pd_network_count)
        ipv6_pd_network_count += 1

        # domain must be a subdomain of the top-level site
        if vlan["domain"] and ((domain not in vlan["domain"]) or (domain == vlan["domain"])):
            raise ValueError(
                f"vlan '{vlan_name}' domain '{vlan['domain']}' is not in top-level domain '{domain}' for vswitch '{vswitch_name}'")

        # single vlan's domain is the site domain
        if not vlan["domain"] and (len(vlans) == 1):
            vlan["domain"] = domain

    if vlan["known_aliases"]:
        _logger.debug("vlan '%s' known_aliases=%s", vlan["name"], vlan["known_aliases"])

    _configure_default_vlan(vswitch)


def _validate_subnet(vswitch_name: str, vlan: dict, ip_version: str, other_subnets: set):
    # ipv4 subnet is required
    # ipv6 subnet is optional; this does not preclude addresses from a prefix assignment
    subnet = vlan.get(ip_version + "_subnet")
    location = f"vswitch['{vswitch_name}'].vlan['{vlan['name']}']"

    if subnet is None:
        if ip_version == "ipv4":
            raise KeyError(f"{location} no {ip_version}_subnet")
        if ip_version == "ipv6":
            vlan["ipv6_subnet"] = None
            return
    elif not isinstance(subnet, str):
        raise ValueError(f"{location} invalid subnet '{subnet}'; it must be a string")

    # remove the subnet if the vlan disables ipv6
    if (ip_version == "ipv6") and (vlan["ipv6_disabled"]):
        vlan["ipv6_subnet"] = None
        return

    try:
        vlan[ip_version + "_subnet"] = subnet = ipaddress.ip_network(str(subnet))
    except ValueError as ve:
        raise ValueError(f"{location} invalid {ip_version}_subnet") from ve

    if (ip_version == "ipv6") and (subnet.prefixlen > 64):
        raise ValueError(f"{location} invalid {ip_version}_subnet; the prefix length cannot be greater than 64")

    if subnet in other_subnets:
        raise ValueError(f"{location} {ip_version}_subnet {subnet} already in use")
    other_subnets.add(subnet)

    # default to DHCP range over all addresses except the router
    min_key = "dhcp_min_address_" + ip_version
    max_key = "dhcp_max_address_" + ip_version

    dhcp_min = vlan.get(min_key, DEFAULT_VLAN_CONFIG[min_key])
    dhcp_max = vlan.get(max_key, DEFAULT_VLAN_CONFIG[max_key])

    dhcp_min = subnet.network_address + dhcp_min
    dhcp_max = subnet.network_address + dhcp_max

    if dhcp_min not in subnet:
        raise ValueError(f"{location} invalid {min_key} '{dhcp_min}'")
    if dhcp_max not in subnet:
        raise ValueError(f"{location} invalid {max_key} '{dhcp_max}'")
    if dhcp_min > dhcp_max:
        raise ValueError(f"{location} {min_key} > {max_key}")


def _validate_dhcp_reservations(vswitch_name: str, vlan: dict):
    reservations = vlan.setdefault("dhcp_reservations", [])
    vlan_path = f"vswitch['{vswitch_name}'].vlan['{vlan['name']}']"

    if not isinstance(reservations, list):
        raise KeyError(f"{vlan_path} dhcp_reservations must be an array")

    for i, res in enumerate(reservations, start=1):
        location = f"{vlan_path}.dhcp_reservations[{i}]"
        parse.non_empty_dict(location, res)

        # hostname & mac address required; ip addresses are not
        _validate_hostname(vlan, res, location)

        if "mac_address" in res:
            parse.validate_mac_address(res["mac_address"], location)
        else:
            raise ValueError(f"{location} no mac_address defined")

        # no ip addresses specified => reservation of hostname only
        _validate_ipaddress("ipv4", vlan, res, location)
        _validate_ipaddress("ipv6", vlan, res, location)

        _validate_aliases(vlan, res, location)


def _validate_static_hosts(vswitch_name: str, vlan: dict):
    hosts = vlan.setdefault("static_hosts", [])
    location = f"vswitch['{vswitch_name}'].vlan['{vlan['name']}']"

    if not isinstance(hosts, list):
        raise KeyError(f"{location} static_hosts must be an array")

    for i, host in enumerate(hosts, start=1):
        location = f"{location}.static_hosts[{i}]"
        parse.non_empty_dict(location, host)

        # hostname and ipv4 address required
        _validate_hostname(vlan, host, location)

        _validate_ipaddress("ipv4", vlan, host, location, required=True)
        _validate_ipaddress("ipv6", vlan, host, location)

        _validate_aliases(vlan, host, location)


def _validate_ipv6_pd_network(vlan: dict, ipv6_pd_networks: set, ipv6_pd_network_count):
    # ensure prefix delegation network is valid and not reused
    if (vlan["ipv6_disabled"]):
        vlan["ipv6_pd_network"] = None
        return

    ipv6_pd_network = vlan.get("ipv6_pd_network", None)
    vlan_name = vlan["name"]
    location = f"vlan['{vlan_name}'].ipv6_pd_network '{ipv6_pd_network}'"

    if ipv6_pd_network is not None:
        if not isinstance(ipv6_pd_network, int):
            raise ValueError(f"{location} must be an integer")
        if ipv6_pd_network < 1:
            raise ValueError(f"{location} must be greater than 0")
    else:
        vlan["ipv6_pd_network"] = ipv6_pd_network = ipv6_pd_network_count

    if ipv6_pd_network in ipv6_pd_networks:
        raise ValueError(f"{location} already used for this vlan")

    ipv6_pd_networks.add(ipv6_pd_network)


def _validate_ipaddress(ip_version: str, vlan: dict, cfg: dict, location: str, required: bool = False):
    key = ip_version + "_address"

    if key not in cfg:
        if required:
            raise ValueError(f"{location}.{key} required")
        else:
            cfg[key] = None
            return

    try:
        address = ipaddress.ip_address(cfg[key])
    except ValueError as ve:
        raise ValueError(f"{location} invalid {key}") from ve
    if address.version != int(ip_version[-1:]):
        raise ValueError(f"{location} invalid {ip_version} address '{cfg[key]}'")

    if (ip_version == "ipv6") and (vlan["ipv6_subnet"] is None):
        _logger.warning("%s ipv6_address %s will be ignored in vlan with no ipv6_subnet defined", location, address)
        return

    if address not in vlan[ip_version + "_subnet"]:
        raise ValueError(f"{location} invalid {key} {address}; it is not in the vlan's subnet")

    cfg[key] = address


def _validate_hostname(vlan: dict, cfg: dict, location: str):
    hostname = parse.non_empty_string("hostname", cfg, location).lower()

    if hostname in vlan["known_aliases"]:
        raise ValueError(f"{location} duplicate hostname or alias '{hostname}'")
    elif dns.invalid_hostname(hostname):
        raise ValueError(f"{location} invalid hostname '{hostname}' defined")

    vlan["known_aliases"].add(hostname)

    # cannot check for duplicate cfg[hosts] / aliases here since hosts have not yet been defined
    cfg["hostname"] = hostname


def _validate_aliases(vlan: dict, cfg: dict, location: str):
    aliases = parse.read_string_list_plurals({"alias", "aliases"}, cfg, location)
    cfg.pop("alias", None)

    cfg["aliases"] = set()

    hostname = cfg["hostname"]
    role_names = roles.names()

    for alias in aliases:
        alias = alias.lower()

        if alias == hostname:
            continue
        elif alias in vlan["known_aliases"]:
            raise ValueError(f"{location} duplicate hostname or alias '{alias}'")
        elif alias in role_names:
            raise ValueError(f"{location} alias cannot be a role name")
        elif dns.invalid_hostname(alias):
            raise ValueError(f"{location} invalid alias '{alias}'")

        vlan["known_aliases"].add(alias)
        cfg["aliases"].add(alias)


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
    "allow_dns_update": bool,
    "dhcp_min_address_ipv4": int,
    "dhcp_max_address_ipv4": int,
    "dhcp6_managed": bool,
    "dhcp_min_address_ipv6": int,
    "dhcp_max_address_ipv6": int
}
