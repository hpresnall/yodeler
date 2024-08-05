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
    """Validate the firewall configuration in the site configuration.

    Note that this function cannot validate rule hostnames since the site's hosts have not yet been defined."""
    if "firewall" not in cfg:
        firewall = cfg["firewall"] = {
            "ipsets4": {},
            "ipsets6": {},
            "static_hosts": {},
            "rules": []
        }
        return

    # firewall config is a dict; rules is a list of dicts
    firewall = parse.non_empty_dict("firewall", cfg.get("firewall"))
    ipsets4, ipsets6 = _parse_ipsets(firewall)

    cfg["firewall"] = {
        "ipsets4": ipsets4,
        "ipsets6": ipsets6,
        "static_hosts": _parse_static_hosts(cfg, firewall),
    }

    # parse rules last since they need ipset and hosts configuration
    cfg["firewall"]["rules"] = _parse_rules(cfg, firewall)  # type: ignore


def _parse_static_hosts(cfg: dict, firewall: dict):
    hosts = firewall.setdefault("static_hosts", [])

    if not isinstance(hosts, list):
        raise KeyError(f"firewall.static_hosts must be a list")

    static_hosts = {}  # map by hostname
    role_names = roles.names()

    for i, host in enumerate(hosts, start=1):
        location = f"firewall.static_hosts[{i}]"
        parse.non_empty_dict(location, host)

        if "hostname" not in host:
            logging.warning(f"skipping {location}; hostname not specified")
            continue

        # lowercase for consistency and to match host & alias configs
        hostname = host["hostname"].lower()

        # cannot validate against cfg["hosts"] here since hosts have not yet been defined
        if dns.invalid_hostname(hostname):
            raise ValueError(f"invalid hostname '{hostname}' for {location}")
        if hostname in static_hosts:
            raise ValueError(f"duplicate hostname '{hostname}' for {location}")
        if hostname in role_names:
            raise ValueError(f"hostname '{hostname}' for {location} conflicts with a role name")

        ipv4_address = ipv6_address = None

        if "ipv4_address" in host:
            try:
                ipv4_address = ipaddress.ip_address(host["ipv4_address"])
            except ValueError as ve:
                raise KeyError(f"invalid ipv4_address for {location}") from ve
        if "ipv6_address" in host:
            try:
                ipv6_address = ipaddress.ip_address(host["ipv6_address"])
            except ValueError as ve:
                raise KeyError(f"invalid ipv6_address for {location}") from ve

        if not ipv4_address and not ipv6_address:
            raise KeyError(f"ipv4 or ipv6 address required for {location}")

        valid_4 = valid_6 = False
        vlan_4 = vlan_6 = {}

        for vswitch in cfg["vswitches"].values():
            for vlan in vswitch["vlans"]:
                # static hostnames are "global" so do not allow duplicates on any vlan
                if hostname in vlan["known_aliases"]:
                    raise ValueError(
                        f"{location} hostname '{hostname}' is already used for a DHCP reservation on vlan '{vlan['name']}'")

                # ip addresses must be in the same valid vlan
                if not valid_4 and ipv4_address and (ipv4_address in vlan["ipv4_subnet"]):
                    valid_4 = True
                    vlan_4 = vlan

                if not valid_6 and ipv6_address and vlan["ipv6_subnet"] and (ipv6_address in vlan["ipv6_subnet"]):
                    valid_6 = True
                    vlan_6 = vlan

        if ipv4_address and not valid_4:
            raise ValueError(f"{location} ipv4_address does not match any vlan subnets")
        if ipv6_address and not valid_6:
            raise ValueError(f"{location} ipv6_address does not match any vlan subnets")
        if vlan_4 and vlan_6 and vlan_4["name"] != vlan_6["name"]:
            raise ValueError(f"ipv6_address is not in the same vlan as the ipv4_address for {location}")

        vlan = vlan_4 if vlan_4 else vlan_6

        if not vlan["routable"]:
            raise ValueError(f"cannot add host {hostname} to non-routable vlan for {location}")

        static_hosts[hostname] = {
            "hostname": hostname,
            "ipv4_address": ipv4_address,
            "ipv6_address": ipv6_address,
            "vlan": vlan["name"]
        }

    return static_hosts


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
        addresses = ipset["addresses"] if "addresses" in ipset else []
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
    # source and destination specify a vswitch/vlan with an optionalhost
    # actions can be a named protocol or a dict of protocol / ports
    for idx, rule in enumerate(rules, start=1):
        location = f"firewall.rules[{idx}]"

        parse.non_empty_dict(location, rule)

        sources = parse.read_dict_list_plurals(
            {"source", "sources"}, rule, location + ".sources")
        rule.pop("source", None)
        destinations = parse.read_dict_list_plurals(
            {"destination", "destinations"}, rule, location + ".destinations")
        rule.pop("destination", None)

        sources4, sources6 = _parse_locations(
            cfg, sources, location + ".sources")
        destinations4, destinations6 = _parse_locations(
            cfg, destinations, location + ".destinations")

        actions = []

        if "allow" in rule:
            actions.extend(_parse_action("allow", rule.get("allow"), location))
        if "forward" in rule:
            actions.extend(_parse_action("forward", rule.get("forward"), location))

        if not actions:
            raise KeyError("no actions defined for " + location)

        parsed_rules.append({
            "comment": rule["comment"] if "comment" in rule else "",
            "ipv4": {"sources": sources4, "destinations": destinations4},
            "ipv6": {"sources": sources6, "destinations": destinations6},
            "actions": actions
        })

    return parsed_rules


def _parse_locations(cfg: dict, locations: list[dict], location: str) -> tuple[list[dict], list[dict]]:
    parsed_locations4 = []
    parsed_locations6 = []

    for idx, loc in enumerate(locations, start=1):
        loc_name = location + f"[{idx}]"

        if "vlan" not in loc:
            raise KeyError(f"vlan must be specified for {location}")

        vlan = loc["vlan"]
        if isinstance(vlan, str):
            if not vlan:
                raise ValueError(f"vlan for {loc_name} cannot be empty")
        elif isinstance(vlan, int):
            if (vlan < 1) or (vlan > 4094):
                raise KeyError(f"invalid vlan id '{vlan}' for {loc_name}")
        else:
            raise KeyError(f"vlan must be string or int for {loc_name}, not {type(vlan)}")

        vlan_obj = None

        if "all" == vlan:
            # no need for further processing
            location_obj = [{"vlan": {"name": "all", "dhcp_reservations": []}}]
            return location_obj, location_obj
        elif "internet" == vlan:
            # not a valid vlan with a hostname, but continue processing for ipsets which can be external
            vlan_obj = {"name": "internet", "dhcp_reservations": []}
            vlan = "internet"
        elif "firewall" == vlan:
            # not a valid vlan, but continue processing other locations
            vlan_obj = {"name": "firewall", "dhcp_reservations": []}
            vlan = "firewall"
        else:
            vswitch = parse.non_empty_string("vswitch", loc, loc_name)

            if vswitch not in cfg["vswitches"]:
                raise KeyError(f"invalid vswitch '{vswitch}' for {loc_name}")

            vlan_obj = vlans.lookup(vlan, cfg["vswitches"][vswitch])
            vlan = vlan_obj["name"]

        parsed_location4 = {"vlan": vlan_obj}
        parsed_location6 = {"vlan": vlan_obj}

        # optional hostname, ipset, or ipaddress
        # if none of these, add a rule for the entire vlan
        if "hostname" in loc:
            if vlan == "internet":
                raise KeyError(f"cannot set hostname when vlan is 'internet' for {loc_name}")
            if vlan == "firewall":
                raise KeyError(f"cannot set hostname when vlan is 'firewall for {loc_name}")
            if "ipset" in loc:
                raise KeyError(f"cannot set hostname and ipset for {loc_name}")
            if ("ipv4_address" in loc) or ("ipv6_address" in loc):
                raise KeyError(f"cannot set hostname and ip address for {loc_name}")

            hostname = parse.non_empty_string("hostname", loc, loc_name).lower()

            # cannot validate against cfg["hosts"] here since hosts have not yet been defined
            parsed_location4["hostname"] = hostname
            parsed_location6["hostname"] = hostname
        elif "ipset" in loc:  # possibly add rule for the ipset
            if vlan == "firewall":
                raise KeyError(f"cannot set ipset when vlan is 'firewall for {loc_name}")

            if ("ipv4_address" in loc) or ("ipv6_address" in loc):
                raise KeyError(f"cannot set ipset and ip address for {loc_name}")

            ipset = parse.non_empty_string("ipset", loc, loc_name).lower()

            if ipset in cfg["firewall"]["ipsets4"]:
                parsed_location4["ipset"] = ipset
            elif ipset in cfg["firewall"]["ipsets6"]:
                parsed_location6["ipset"] = ipset
            else:
                raise ValueError(f"uknown ipset '{ipset}' for {loc_name}")
        else:
            if vlan == "firewall":
                if ("ipv4_address" in loc) or ("ipv6_address" in loc):
                    raise KeyError(f"cannot set ip address when vlan is 'firewall for {loc_name}")
            elif "ipv4_address" in loc:
                try:
                    address = ipaddress.ip_address(loc["ipv4_address"])
                except ValueError as ve:
                    raise KeyError(f"invalid ipv4 address '{loc['ipv4_address']}' for {loc_name}") from ve
                if not isinstance(address, ipaddress.IPv4Address):
                    raise ValueError(f"invalid ipv4 address '{loc['ipv4_address']}' for {loc_name}")
                if vlan_obj and (address not in vlan_obj["ipv4_subnet"]):
                    raise ValueError(
                        f"invalid ipv4 address '{loc['ipv4_address']}' for {loc_name}; it is not in vlan '{vlan}'")
                parsed_location4["ipaddress"] = str(address)

            if "ipv6_address" in loc:
                try:
                    address = ipaddress.ip_address(loc["ipv6_address"])
                except ValueError as ve:
                    raise KeyError(f"invalid ipv6 address '{loc['ipv6_address']}' for {loc_name}") from ve
                if not isinstance(address, ipaddress.IPv6Address):
                    raise ValueError(f"invalid ipv6 address '{loc['ipv6_address']}' for {loc_name}")
                if vlan_obj and vlan_obj["ipv6_subnet"] and (address not in vlan_obj["ipv6_subnet"]):
                    raise ValueError(
                        f"invalid ipv6 address '{loc['ipv6_address']}' for {loc_name}; it is not in vlan '{vlan}'")
                parsed_location6["ipaddress"] = str(address)

                if "ipaddress" not in parsed_location4:
                    parsed_location4 = None  # ipv6 set but not ipv4 => ipv6 only rule
            elif "ipaddress" in parsed_location4:
                parsed_location6 = None  # ipv4 set but not ipv6 => ipv4 only rule

        if parsed_location4:
            parsed_locations4.append(parsed_location4)
        if parsed_location6:
            parsed_locations6.append(parsed_location6)

    return parsed_locations4, parsed_locations6


named_protocols = ["ping", "ssh", "telnet", "dns", "ntp", "samba", "web", "ftp", "mail", "pop3", "imap", "imaps"]


def _parse_action(name: str, actions: list, location: str) -> list[dict]:
    base = location + "." + name
    actions = parse.non_empty_list(location, actions)
    parsed_actions = []

    for i, action in enumerate(actions):
        location = f"{base}[{i}]"
        # named protocol; hosts are responsible for converting the protocol to a valid rule
        if isinstance(action, str):
            action = action.lower()
            if action not in named_protocols:
                raise ValueError(
                    f"invalid {name} '{action}' for {location}; it is not a valid protocol name")

            parsed_actions.append({"action": name, "type": "named", "protocol": action, "comment": ""})
        elif isinstance(action, dict):
            # dict of protocol & ports
            protocol = parse.non_empty_string("proto", action, location)

            if protocol not in ("tcp", "udp"):
                raise ValueError(
                    f"protocol for {location} must be 'tcp' or 'udp'")

            # allow singular and plural
            if "port" in action:
                unparsed_ports = action["port"]
            elif "ports" in action:
                unparsed_ports = action["ports"]
            else:
                raise KeyError(f"no port defined for {location}")

            # port can be an int, a string with ':' or '-' for a range, or a list
            if isinstance(unparsed_ports, int):
                if unparsed_ports < 1:
                    raise ValueError(f"port for {location} must be greater than 0")
                ports = [str(unparsed_ports)]
            elif isinstance(unparsed_ports, str):
                if not unparsed_ports:
                    raise ValueError(f"port for {location} cannot be empty")
                ports = [unparsed_ports.replace("-", ":")]
            elif isinstance(unparsed_ports, list):
                ports = []
                for j, port in enumerate(unparsed_ports, start=1):
                    if isinstance(port, int):
                        if port < 1:
                            raise ValueError(f"port {j} for {location} must be greater than 0")
                        ports.append(str(port))
                    elif isinstance(port, str):
                        if not port:
                            raise ValueError(f"port {j} for {location} cannot be empty")
                        ports.append(port.replace("-", ":"))
                    else:
                        raise ValueError(
                            f"port {j} for {location} must be a string or int, not {type(port)}")
            else:
                raise ValueError(
                    f"port for {location} must be a string or int, not {type(unparsed_ports)}")

            comment = action["comment"] if "comment" in action else ""

            parsed_actions.append({"action": name, "type": "protoport",
                                  "protocol": protocol, "ports": ports, "comment": comment})
        else:
            raise ValueError(
                f"{location}.allow[{i+1}] must be a string or dict, not {type(action)}")

    return parsed_actions


def validate_rule_hostnames(cfg: dict):
    """Validates that all hostnames referenced in firewall rules exist.
    Also ensures that all firewall rules are written with a hostname and not an alias.

    Must be called after all hosts for the site are loaded."""
    for i, rule in enumerate(cfg["firewall"]["rules"], start=1):
        _validate_location_hostname(cfg, rule, i, "ipv4", "sources")
        _validate_location_hostname(cfg, rule, i, "ipv4", "destinations")
        _validate_location_hostname(cfg, rule, i, "ipv6", "sources")
        _validate_location_hostname(cfg, rule, i, "ipv6", "destinations")


def _validate_location_hostname(cfg: dict, rule: dict, idx: int, ip_version: str, src_or_dest: str):
    # allow 'hostname' in firewall rules to be an alias, static hostname mapping or DHCP reservations
    # determine the real value and map the rule to an actual hostname
    locations_to_remove = []

    # rule deleted by previous call
    if ip_version not in rule:
        return

    for i, location in enumerate(rule[ip_version][src_or_dest], start=1):
        if not "hostname" in location:
            continue

        loc_name = f"firewall.rule[{idx}].{src_or_dest}[{i}]"
        hostname = location["hostname"]
        vlan = location["vlan"]  # already validated in _parse_locations()

        host = hostname in cfg["hosts"]

        if host:
            _validate_host_vlan(cfg, hostname, vlan, loc_name)
            _logger.debug("%s found '%' as a top-level host", loc_name, hostname)
            continue
        # else hostname is not a host, check aliases

        for h in cfg["hosts"].values():
            if hostname in h["aliases"]:
                host = True
                hostname = location["hostname"] = h["hostname"]
                _logger.debug("%s found '%s' as a top-level host alias for '%s'", loc_name, hostname, h["hostname"])
                break

        if host:
            _validate_host_vlan(cfg, hostname, vlan, loc_name)
            continue
        # else not an alias, check static_hosts

        if hostname in cfg["firewall"]["static_hosts"]:
            address = cfg["firewall"]["static_hosts"][hostname][ip_version + "_address"]
            if address:
                if address not in vlan[ip_version + "_subnet"]:
                    raise ValueError(
                        f"{loc_name} invalid static host {hostname}; it does not have an address in vlan '{vlan['name']}'")
                _logger.debug("%s found '%s' as a firewall static_host", loc_name, hostname)
            else:
                locations_to_remove.append(i-1)
                _logger.debug("%s found '%s' as a firewall static_host without an %s address; removing rule",
                              loc_name, hostname, ip_version)
            continue
        # else not a static host, check dhcp rerservations

        for reservation in vlan["dhcp_reservations"]:
            if (hostname == reservation["hostname"]):
                host = True
            elif hostname in reservation["aliases"]:
                location["hostname"] = reservation["hostname"]
                host = True

            if host:
                if reservation[ip_version + "_address"]:
                    # reservation address must be in vlan; no need to recheck here
                    _logger.debug("%s found '%s' as a dhcp reservation", loc_name, hostname)
                else:
                    locations_to_remove.append(i-1)
                    _logger.debug("%s found '%s' as a dhcp reservation without an %s address; removing rule",
                                  loc_name, hostname, ip_version)
                break

        if host:
            _logger.debug("%s found '%s' as a DHCP reservation in vlan '%s'", loc_name, hostname, vlan["name"])
            continue
        else:
            raise ValueError(
                f"invalid hostname '{hostname}' in {loc_name}; could not find a DHCP reservation in vlan '{vlan['name']}'")
    # for locations

    deleted_locations = []

    for location in locations_to_remove:
        deleted_locations.append(rule[ip_version][src_or_dest].pop(location))

    # if there is no src_or_dest, the whole rule is unnecessary
    if not rule[ip_version][src_or_dest]:
        del rule[ip_version]
        _logger.debug(
            f"removing firewall.rule[{idx}] for with no valid {src_or_dest} for {ip_version} in {deleted_locations}")


def _validate_host_vlan(cfg: dict, hostname: str, vlan: dict, loc_name: str):
    valid_vlan = False
    for iface in cfg["hosts"][hostname]["interfaces"]:
        if iface["vlan"]["name"] == vlan["name"]:
            valid_vlan = True
    if not valid_vlan:
        raise ValueError(f"{loc_name} invalid host {hostname}; it has no interface defined in vlan '{vlan['name']}'")
