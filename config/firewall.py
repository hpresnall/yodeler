"""Handles parsing and validating firewall configuration from site YAML files."""
import logging
import ipaddress

import util.address as address
import util.dns as dns
import util.parse as parse

import role.roles as roles

import config.vlan as vlans


_logger = logging.getLogger(__name__)


def validate(cfg: dict):
    """Validate the firewall rules defined for the site.

    This function should be called before the site's hosts are loaded.
    However, this means that this function cannot validate hostnames or aliases in rules.
    These will be validated in validate_rule_hostnames()."""
    if "firewall" not in cfg:
        firewall = cfg["firewall"] = {
            "ipsets4": {},
            "ipsets6": {},
            "rules": []
        }
        return

    # firewall config is a dict; rules is a list of dicts
    firewall = parse.non_empty_dict("firewall", cfg.get("firewall"))
    ipsets4, ipsets6 = _parse_ipsets(firewall)

    cfg["firewall"] = {
        "ipsets4": ipsets4,
        "ipsets6": ipsets6
    }

    # parse rules last since they need ipset and hosts configuration
    cfg["firewall"]["rules"] = _parse_rules(cfg, firewall)  # type: ignore


def _parse_ipsets(firewall: dict) -> tuple[dict, dict]:
    if not "ipsets" in firewall:
        return {}, {}

    ipsets = parse.non_empty_list("firewall['ipsets']", firewall.get("ipsets"))

    # return a dict of ipset name to object
    ipsets4 = {}
    ipsets6 = {}

    for idx, ipset in enumerate(ipsets, start=1):
        if not isinstance(ipset, dict):
            raise ValueError(f"ipsets[{idx}] must be an object")

        name = parse.non_empty_string("name", ipset, f"ipset[{idx}]").lower()
        addresses = ipset.get("addresses", [])
        parse.non_empty_list(f"ipsets[{idx}]['addresses']", addresses)

        try:
            version, is_networks = address.check_addresses(addresses)
        except ValueError as ve:
            raise ValueError(f"ipsets[{idx}]['addresses']") from ve

        n = len(addresses)

        data = ipsets4 if version == 4 else ipsets6
        # data for ipset command
        data[name] = {
            "family": "inet" if version == 4 else "inet6",
            # only use hash ipset types, either net or ip
            "type": "net" if is_networks else "ip",
            # round up to nearest power of 2 for hashsize
            "hashsize": 1 if n == 0 else 2**(n - 1).bit_length(),
            "addresses": addresses
        }

    return ipsets4, ipsets6


def _parse_rules(cfg: dict, firewall: dict) -> list[dict]:
    if not "rules" in firewall:
        return []

    # rules is a list of dicts
    rules = parse.non_empty_list("rules", firewall.get("rules"))
    parsed_rules = []

    # each rule should be a pair of source(s)/destination(s) plus a list of actions
    # source and destination specify a vswitch/vlan with an optional host
    # actions can be a named protocol or a dict of protocol / ports
    for idx, rule in enumerate(rules, start=1):
        location = f"firewall.rules[{idx}]"

        parse.non_empty_dict(location, rule)

        sources = parse.read_dict_list_plurals({"source", "sources"}, rule, location + ".sources")
        destinations = parse.read_dict_list_plurals({"destination", "destinations"}, rule, location + ".destinations")

        sources = _parse_locations(cfg, sources, location + ".sources")
        destinations = _parse_locations(cfg, destinations, location + ".destinations")

        actions = []

        if ("allow-all" in rule) and rule["allow-all"]:  # allow-all: true supercedes other rules
            actions.append({"action": "allow-all", "type": "allow-all", "ipv4": True, "ipv6": True})
        elif "allow" in rule:
            actions.extend(_parse_action("allow", rule.get("allow"), location))
        elif "forward" in rule:  # ignore forward if allow also set
            actions.extend(_parse_action("forward", rule.get("forward"), location))

        if not actions:
            raise KeyError("no actions defined for " + location)

        parsed_rule = {
            "comment": rule.get("comment", ""),
            "sources": sources,
            "destinations": destinations,
            "actions": actions
        }

        parsed_rules.append(parsed_rule)

    return parsed_rules


def _parse_locations(cfg: dict, locations: list[dict], location: str) -> list[dict]:
    parsed_locations = []

    for idx, loc in enumerate(locations, start=1):
        loc_name = location + f"[{idx}]"

        if "vlan" not in loc:
            raise KeyError(f"{loc_name} vlan must be specified")

        vlan = loc["vlan"]

        if isinstance(vlan, str):
            if not vlan:
                raise ValueError(f"vlan for {loc_name} cannot be empty")
        elif isinstance(vlan, int):
            if (vlan < 1) or (vlan > 4094):
                raise ValueError(f"{loc_name} invalid vlan id '{vlan}'")
        else:
            raise ValueError(f"{loc_name} vlan must be string or int, not {type(vlan)}")

        vlan_obj = None

        if "all" == vlan:
            # no need for further processing
            return [_all]
        elif "internet" == vlan:
            # not a valid vlan with a hostname, but continue processing for ipsets which can be external
            vlan_obj = _internet["vlan"]
            vlan = vlan_obj["name"]
        elif "firewall" == vlan:
            # not a valid vlan with a hostname, but continue processing other locations
            vlan_obj = _fw["vlan"]
            vlan = vlan_obj["name"]
        else:
            vswitch = parse.non_empty_string("vswitch", loc, loc_name + f" for vlan '{vlan}'")

            if vswitch not in cfg["vswitches"]:
                raise ValueError(f"{loc_name} invalid vswitch '{vswitch}'")

            try:
                vlan_obj = vlans.lookup(vlan, cfg["vswitches"][vswitch])
            except Exception as e:
                raise ValueError(f"{loc_name} invalid vlan '{vlan}'", e)

            vlan = vlan_obj["name"]

            if not vlan_obj["routable"]:
                raise ValueError(f"{loc_name} invalid vlan '{vlan}'; it is not routable")

        parsed_location = {"vlan": vlan_obj, "ipv4": True, "ipv6": True}

        # optional hostname, ipset, or ipaddress
        # if none of these, add a rule for the entire vlan
        if "hostname" in loc:
            if vlan == "firewall":
                raise KeyError(f"{loc_name} cannot set hostname when vlan is 'firewall'")
            elif "ipset" in loc:
                raise KeyError(f"{loc_name} cannot set hostname and ipset")
            elif ("ipv4_address" in loc) or ("ipv6_address" in loc):
                raise KeyError(f"{loc_name} cannot set hostname and ip address")

            hostname = parse.non_empty_string("hostname", loc, loc_name).lower()

            if (vlan == "internet"):
                found = False
                for ext in cfg["external_hosts"]:
                    if hostname in ext["hostnames"]:
                        found = True
                        break
                if not found:
                    raise ValueError(f"{location} hostname '{hostname}' is not defined in external_hosts")

            # cannot validate against cfg["hosts"] here since hosts have not yet been defined
            parsed_location["hostname"] = hostname
        elif "ipset" in loc:  # possibly add rule for the ipset
            if vlan == "firewall":
                raise KeyError(f"{loc_name} cannot set ipset when vlan is 'firewall'")
            # allow internet since ipsets can refer to external addresses
            elif ("ipv4_address" in loc) or ("ipv6_address" in loc):
                raise KeyError(f"{loc_name} cannot set ipset and ip address")

            ipset = parse.non_empty_string("ipset", loc, loc_name).lower()

            if ipset in cfg["firewall"]["ipsets4"]:
                parsed_location["ipset"] = ipset
                parsed_location["ipv6"] = False
            elif ipset in cfg["firewall"]["ipsets6"]:
                parsed_location["ipset"] = ipset
                parsed_location["ipv4"] = False
            else:
                raise ValueError(f"{loc_name} uknown ipset '{ipset}'")
        else:  # ip address
            if vlan == "firewall":
                if ("ipv4_address" in loc) or ("ipv6_address" in loc):
                    raise KeyError(f"{loc_name} cannot set ip address when vlan is 'firewall'")

            if "ipv4_address" in loc:
                try:
                    address = ipaddress.ip_address(loc["ipv4_address"])
                except ValueError as ve:
                    raise ValueError(f"{loc_name} invalid ipv4 address '{loc['ipv4_address']}'") from ve
                if not isinstance(address, ipaddress.IPv4Address):
                    raise ValueError(f"{loc_name} invalid ipv4 address '{loc['ipv4_address']}'")

                # address must be in the vlan or not in any vlans
                if vlan == "internet":
                    _check_internet_address(cfg, address, location)
                elif address not in vlan_obj["ipv4_subnet"]:
                    raise ValueError(
                        f"{loc_name} invalid ipv4 address '{loc['ipv4_address']}'; it is not in vlan '{vlan}'")

                parsed_location["ipv4_address"] = str(address)

                # no address => location if for entire vlan; continue to allow ipv4 access
                if not "ipv6_address" in loc:
                    parsed_location["ipv6"] = False

            if "ipv6_address" in loc:
                try:
                    address = ipaddress.ip_address(loc["ipv6_address"])
                except ValueError as ve:
                    raise ValueError(f"{loc_name} invalid ipv6 address '{loc['ipv6_address']}'") from ve
                if not isinstance(address, ipaddress.IPv6Address):
                    raise ValueError(f"{loc_name} invalid ipv6 address '{loc['ipv6_address']}'")

                # address must be in the vlan or not in any vlans
                if vlan == "internet":
                    _check_internet_address(cfg, address, location)
                elif vlan_obj["ipv6_subnet"] and (address not in vlan_obj["ipv6_subnet"]):
                    raise ValueError(
                        f"{loc_name} invalid ipv6 address '{loc['ipv6_address']}'; it is not in vlan '{vlan}'")

                parsed_location["ipv6_address"] = str(address)

                # no address => location if for entire vlan; continue to allow ipv4 access
                if not "ipv4_address" in loc:
                    parsed_location["ipv4"] = False

        parsed_locations.append(parsed_location)

    return parsed_locations


def _parse_action(action_type: str, actions: str | dict | list, location: str) -> list[dict]:
    base = location + "." + action_type

    # accept single string or obj
    if isinstance(actions, str):
        return [action_service(action_type, actions, base)]
    elif isinstance(actions, dict):
        return [_action_proto_port(action_type, actions, base)]
    # else assume list

    actions = parse.non_empty_list(location, actions)
    parsed_actions = []

    for i, action in enumerate(actions, start=1):
        location = f"{base}[{i}]"

        if isinstance(action, str):
            parsed_actions.append(action_service(action_type, action, location))
        elif isinstance(action, dict):
            parsed_actions.append(_action_proto_port(action_type, action, location))
        else:
            raise ValueError(
                f"{location} must be a string or dict, not {type(action)}")

    return parsed_actions


def validate_full_site(cfg: dict):
    """Validates that all hostnames referenced in firewall rules exist. Converts all aliases to the actual hostname.

    Must be called after all hosts for the site are loaded."""
    rules_to_delete = []

    for i, rule in enumerate(cfg["firewall"]["rules"], start=1):
        _validate_location_hostname(cfg, rule, i, "sources")
        _validate_location_hostname(cfg, rule, i, "destinations")

        # no source or destination left, delete the entire rule
        if not rule["sources"] or not rule["destinations"]:
            rules_to_delete.append(i-1)

    # reverse so pop() does not cause reordering
    rules_to_delete.reverse()

    for rule in rules_to_delete:
        cfg["firewall"]["rules"].pop(rule)


def _validate_location_hostname(cfg: dict, rule: dict, idx: int, src_or_dest: str):
    # allow 'hostname' in firewall rules to be an alias, static hostname mapping or DHCP reserved name
    # determine the real value and map the rule to the actual hostname

    # if the host is defined statically or from DHCP, remove rules without an ip address defined for this version
    locations_to_remove = []

    for i, location in enumerate(rule[src_or_dest], start=1):
        if not "hostname" in location:
            continue

        loc_name = f"firewall.rule[{idx}].{src_or_dest}[{i}]"
        hostname = location["hostname"]
        vlan = location["vlan"]  # already validated in _parse_locations()

        found = hostname in cfg["hosts"]

        if found:
            _logger.debug("%s found '%s' as a top-level host", loc_name, hostname)

            if not _validate_host_vlan(cfg, hostname, vlan, loc_name, location):
                locations_to_remove.append(i-1)
                _logger.debug("%s removing rule for host '%s' without any ip addresses", loc_name, hostname)
            continue
        # else hostname is not a host, check aliases

        for h in cfg["hosts"].values():
            if hostname in h["aliases"]:
                found = True
                _logger.debug("%s found '%s' as a top-level host alias for '%s'", loc_name, h["hostname"], hostname)
                location["hostname"] = hostname = h["hostname"]  # update alias to actual hostname
                break

        if found:
            if not _validate_host_vlan(cfg, hostname, vlan, loc_name, location):
                locations_to_remove.append(i-1)
                _logger.debug("%s removing rule for host '%s' without any ip addresses", loc_name, hostname)
            continue
        # else not an alias, check external_hosts

        # hostnames in the internet vlan have already been against external_hosts
        # but recheck here for incorrect use of external_hosts in other vlans
        # also disable ipv6 here for consistency with other host types
        for ext in cfg["external_hosts"]:
            if hostname in ext["hostnames"]:
                found = True
                # external hosts must have an ipv4 address; ipv6 is optional
                _logger.debug("%s found '%s' as an external host", loc_name, hostname)
                if not ext["ipv6_address"]:
                    _logger.debug("%s external host '%s' has no ipv6 address; disabling ipv6 rule", loc_name, hostname)
                    location["ipv6"] = False
                break

        if found:
            if vlan["name"] != "internet":
                raise ValueError(
                    f"{loc_name} invalid hostname '{hostname}'; the vlan must be 'internet' for externally defined hosts")
            _logger.debug("%s found '%s' as an external_host for '%s'", loc_name, hostname, h["hostname"])
            continue
        # else check vlan DHCP reservations and static hosts

        if hostname not in vlan["known_aliases"]:
            raise ValueError(
                f"{loc_name} invalid hostname '{hostname}'; could not find as a DHCP reservation or static host in vlan '{vlan['name']}', or as an external host")
        # else vlan defines hostname; now find it

        for vlan_host in vlan["dhcp_reservations"] + vlan["static_hosts"]:
            if (hostname == vlan_host["hostname"]):
                _logger.debug("%s found '%s' as a host in vlan '%s'", loc_name, hostname, vlan["name"])
                found = True
            elif hostname in vlan_host["aliases"]:
                _logger.debug("%s found '%s' as a host alias for '%s' in vlan '%s'",
                              loc_name, hostname, vlan_host["hostname"], vlan["name"])
                location["hostname"] = hostname = vlan_host["hostname"]  # update alias to actual hostname
                found = True

            if found:
                # reservation address must be in vlan; no need to recheck here
                # but, reservation could be for hostname only; remove location if no address defined
                if not vlan_host["ipv4_address"]:
                    _logger.debug("%s vlan host '%s' has no ipv4 address; disabling ipv4 rule", loc_name, hostname)
                    location["ipv4"] = False
                if not vlan_host["ipv6_address"]:
                    _logger.debug("%s vlan host '%s' has no ipv6 address; disabling ipv6 rule", loc_name, hostname)
                    location["ipv6"] = False
                    # reservation address must be in vlan; no need to recheck here

                if not location["ipv4"] and not location["ipv6"]:
                    locations_to_remove.append(i-1)
                    _logger.debug("%s removing rule for vlan host '%s' without any ip addresses", loc_name, hostname)
                break

        if not found:
            # if this happens, vlan["known_aliases"] does not line up with the rest of the vlan config
            raise ValueError(
                f"{loc_name} invalid hostname '{hostname}'; could not find as a DHCP reservation or static host in vlan '{vlan['name']}', or as an external host")
    # for locations

    # reverse so pop() does not cause reordering
    locations_to_remove.reverse()

    for location in locations_to_remove:
        rule[src_or_dest].pop(location)


def _check_internet_address(cfg: dict, address: ipaddress.IPv4Address | ipaddress.IPv6Address, location: str):
    # confirm ip address is not in any internal vlan
    for vswitch in cfg["vswitches"].values():
        for vlan in vswitch["vlans"]:
            if isinstance(address, ipaddress.IPv4Address):
                subnet_key = "ipv4_subnet"
            elif isinstance(address, ipaddress.IPv6Address):
                subnet_key = "ipv6_subnet"

            if address in vlan[subnet_key]:
                raise ValueError(f"{location} ip address '{address}' is in vlan {vlan['name']}, not on the internet")


def _validate_host_vlan(cfg: dict, hostname: str, vlan: dict, loc_name: str, location: dict) -> bool:
    # ensure host has an interface on the rule's vlan
    # disable location for ip versions if DHCP or no ipv6
    for iface in cfg["hosts"][hostname]["interfaces"]:
        if iface["vlan"]["name"] == vlan["name"]:
            if iface["ipv4_address"] == "dhcp":
                _logger.debug("%s host '%s' has a DHCP ipv4 address on interface '%s' for vlan '%s'; disabling ipv4 rule",
                              loc_name, hostname, iface["name"], vlan["name"])
                location["ipv4"] = False

            if not iface["ipv6_address"]:
                _logger.debug("%s host '%s' does not have an ipv6 address on interface '%s' for vlan '%s'; disabling ipv6 rule",
                              loc_name, hostname, iface["name"], vlan["name"])
                location["ipv6"] = False

            # true if any ip address
            return location["ipv4"] or location["ipv6"]

    raise ValueError(f"{loc_name} invalid host '{hostname}'; it has no interface defined in vlan '{vlan['name']}'")


# functions to build rules; for use in role.additional_configuration()
def add_rule(cfg: dict, sources: list[dict], destinations: list[dict], actions: list[dict], comment: str = ""):
    if not cfg:
        raise ValueError("cfg cannot be empty")
    if not sources:
        raise ValueError("sources cannot be empty")
    if not destinations:
        raise ValueError("destinations cannot be empty")
    if not actions:
        raise ValueError("actions cannot be empty")

    rule = {
        "comment": comment,
        "sources": sources,
        "destinations": destinations,
        "actions": actions
    }

    cfg["firewall"]["rules"].append(rule)


def location_all() -> dict:
    return _all


def location_internet() -> dict:
    return _internet


def location_firewall() -> dict:
    return _fw


def location(vlan: dict, hostname: str = "", ipv4: bool = True,  ipv6: bool = True) -> dict:
    parse.non_empty_dict("vlan", vlan)

    location: dict = {
        "vlan": vlan,
        "ipv4": ipv4,
        "ipv6": ipv6,
    }

    if hostname:
        location["hostname"] = hostname

    return location


def destinations_from_interfaces(interfaces: list[dict], hostname: str, ipv4: bool = True,  ipv6: bool = True) -> list[dict]:
    # create a location to the host's interfaces for each routable vlan
    destinations = []

    for iface in interfaces:
        if (iface["type"] not in {"std", "vlan"}) or (not iface["vlan"]["routable"]):
            continue

        # other hosts on the same non-routable vlan will be able to access regardless
        if not iface["vlan"]["routable"]:
            continue

        destinations.append(location(iface["vlan"], hostname, ipv4=ipv4, ipv6=ipv6))

    return destinations


def allow_service(service: str, location: str = "", ipv4: bool = True,  ipv6: bool = True) -> dict:
    return action_service("allow", service, location, ipv4, ipv6)


def action_service(action: str, service: str, location: str = "", ipv4: bool = True,  ipv6: bool = True) -> dict:
    # action is a named service; router role config is responsible for converting the service to a valid proto & port
    if location:
        location += " "

    if not action:
        raise ValueError(f"{location}action must be specified")
    if not service:
        raise ValueError(f"{location}service must be specified")
    if not ipv4 and not ipv6:
        raise ValueError(f"{location}ipv4 and ipv6 cannot both be false")
    if service not in named_services:
        raise ValueError(f"{location}invalid {action} service '{service}'; it is not a valid service name")
    if action not in ["allow", "forward"]:
        raise ValueError(f"{location} action must be 'allow' or 'forward'")

    return {
        "action": action,
        "type": "named",
        "protocol": service,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "comment": ""
    }


def allow_proto_port(port: int|str|list, proto: str="tcp", location:str="", comment:str="", ipv4: bool = True,  ipv6: bool = True) -> dict:
    return _action_proto_port("allow", {"proto": proto, "port": port, "comment": comment}, location, ipv4, ipv6)


def _action_proto_port(action: str, proto_port: dict, location="", ipv4: bool = True,  ipv6: bool = True) -> dict:
    # action is a dict of protocol & ports
    # port(s) can be an int or a range separated by - or :
    if not location:
        location = str(proto_port)

    if not action:
        raise ValueError(f"{location}action must be specified")
    if not ipv4 and not ipv6:
        raise ValueError(f"{location} ipv4 and ipv6 cannot both be false")
    if action not in ["allow", "forward"]:
        raise ValueError(f"{location} action must be 'allow' or 'forward'")

    parse.non_empty_dict("proto_port" if location == "{}" else location, proto_port)

    protocol = parse.non_empty_string("proto", proto_port, location)

    if protocol not in ("tcp", "udp"):
        raise ValueError(f"{location}.proto must be 'tcp' or 'udp'")

    # allow singular and plural
    if "port" in proto_port:
        unparsed_ports = proto_port["port"]
    elif "ports" in proto_port:
        unparsed_ports = proto_port["ports"]
    else:
        raise KeyError(f"no port defined for {location}")

    # port can be an int, a string with ':' or '-' for a range, or a list
    if isinstance(unparsed_ports, int):
        if unparsed_ports < 1:
            raise ValueError(f"{location}.port must be greater than 0")
        ports = [str(unparsed_ports)]
    elif isinstance(unparsed_ports, str):
        if not unparsed_ports:
            raise ValueError(f"{location}.port cannot be empty")
        ports = [unparsed_ports.replace("-", ":")]
    elif isinstance(unparsed_ports, list):
        ports = []
        for j, port in enumerate(unparsed_ports, start=1):
            if isinstance(port, int):
                if port < 1:
                    raise ValueError(f"{location}.port[{j}] must be greater than 0")
                ports.append(str(port))
            elif isinstance(port, str):
                if not port:
                    raise ValueError(f"{location}.port[{j}] cannot be empty")
                ports.append(port.replace("-", ":"))
            else:
                raise ValueError(
                    f"{location}.port[{j}] must be a string or int, not {type(port)}")
    else:
        raise ValueError(
            f"{location}.port must be a string or int, not {type(unparsed_ports)}")

    comment = proto_port.get("comment", "")

    return {
        "action": action,
        "type": "protoport",
        "protocol": protocol,
        "ports": ports,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "comment": comment
    }


named_services = ["ping", "traceroute", "ssh", "telnet", "dns", "dhcp",
                  "ntp", "samba", "web", "ftp", "mail", "pop3", "imap", "imaps"]

# fake vlan configs for firewall rule source / destinations
_all = {"vlan": {"name": "all", "dhcp_reservations": []}, "ipv4": True, "ipv6": True}
_internet = {"vlan": {"name": "internet", "dhcp_reservations": [], "known_aliases": []}, "ipv4": True, "ipv6": True}
_fw = {"vlan": {"name": "firewall", "dhcp_reservations": []}, "ipv4": True, "ipv6": True}
