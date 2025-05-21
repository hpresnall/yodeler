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

        sources4, sources6 = _parse_locations(cfg, sources, location + ".sources")
        destinations4, destinations6 = _parse_locations(cfg, destinations, location + ".destinations")

        actions = []

        if ("allow-all" in rule) and rule["allow-all"]:  # allow-all: true supercedes other rules
            actions.append({"action": "allow-all", "type": "allow-all"})
        elif "allow" in rule:
            actions.extend(_parse_action("allow", rule.get("allow"), location))
        elif "forward" in rule:  # ignore forward if allow also set
            actions.extend(_parse_action("forward", rule.get("forward"), location))

        if not actions:
            raise KeyError("no actions defined for " + location)

        parsed_rule = {
            "comment": rule.get("comment", ""),
            "ipv4": {"sources": sources4, "destinations": destinations4},
            "ipv6": {"sources": sources6, "destinations": destinations6},
            "actions": actions
        }

        parsed_rules.append(parsed_rule)

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
            # not a valid vlan with a hostname, but continue processing other locations
            vlan_obj = {"name": "firewall", "dhcp_reservations": []}
            vlan = "firewall"
        else:
            vswitch = parse.non_empty_string("vswitch", loc, loc_name)

            if vswitch not in cfg["vswitches"]:
                raise KeyError(f"{loc_name} invalid vswitch '{vswitch}'")

            vlan_obj = vlans.lookup(vlan, cfg["vswitches"][vswitch])
            vlan = vlan_obj["name"]

        parsed_location4 = {"vlan": vlan_obj}
        parsed_location6 = {"vlan": vlan_obj}

        # optional hostname, ipset, or ipaddress
        # if none of these, add a rule for the entire vlan
        if "hostname" in loc:
            if vlan == "firewall":
                raise KeyError(f"{loc_name} cannot set hostname when vlan is 'firewall'")
            elif vlan == "internet":
                raise KeyError(f"{loc_name} cannot set hostname when vlan is 'internet'")
            elif "ipset" in loc:
                raise KeyError(f"{loc_name} cannot set hostname and ipset")
            elif ("ipv4_address" in loc) or ("ipv6_address" in loc):
                raise KeyError(f"{loc_name} cannot set hostname and ip address")

            hostname = parse.non_empty_string("hostname", loc, loc_name).lower()

            # cannot validate against cfg["hosts"] here since hosts have not yet been defined
            parsed_location4["hostname"] = hostname
            parsed_location6["hostname"] = hostname
        elif "ipset" in loc:  # possibly add rule for the ipset
            if vlan == "firewall":
                raise KeyError(f"{loc_name} cannot set ipset when vlan is 'firewall'")
            # allow internet since ipsets can refer to external addresses
            elif ("ipv4_address" in loc) or ("ipv6_address" in loc):
                raise KeyError(f"{loc_name} cannot set ipset and ip address")

            ipset = parse.non_empty_string("ipset", loc, loc_name).lower()

            if ipset in cfg["firewall"]["ipsets4"]:
                parsed_location4["ipset"] = ipset
            elif ipset in cfg["firewall"]["ipsets6"]:
                parsed_location6["ipset"] = ipset
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
                    raise KeyError(f"{loc_name} invalid ipv4 address '{loc['ipv4_address']}'") from ve
                if not isinstance(address, ipaddress.IPv4Address):
                    raise ValueError(f"{loc_name} invalid ipv4 address '{loc['ipv4_address']}'")
                if vlan_obj and (address not in vlan_obj["ipv4_subnet"]):
                    raise ValueError(
                        f"{loc_name} invalid ipv4 address '{loc['ipv4_address']}'; it is not in vlan '{vlan}'")
                parsed_location4["ipaddress"] = str(address)

            if "ipv6_address" in loc:
                try:
                    address = ipaddress.ip_address(loc["ipv6_address"])
                except ValueError as ve:
                    raise KeyError(f"{loc_name} invalid ipv6 address '{loc['ipv6_address']}'") from ve
                if not isinstance(address, ipaddress.IPv6Address):
                    raise ValueError(f"{loc_name} invalid ipv6 address '{loc['ipv6_address']}'")
                if vlan_obj and vlan_obj["ipv6_subnet"] and (address not in vlan_obj["ipv6_subnet"]):
                    raise ValueError(
                        f"{loc_name} invalid ipv6 address '{loc['ipv6_address']}'; it is not in vlan '{vlan}'")
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

    for i, action in enumerate(actions, start=1):
        location = f"{base}[{i}]"
        if isinstance(action, str):
            # named protocol; router role config is responsible for converting the protocol to a valid rule
            action = action.lower()

            if action not in named_protocols:
                raise ValueError(f"invalid {name} '{action}' for {location}; it is not a valid protocol name")

            parsed_actions.append({"action": name, "type": "named", "protocol": action, "comment": ""})
        elif isinstance(action, dict):
            # dict of protocol & ports
            protocol = parse.non_empty_string("proto", action, location)

            if protocol not in ("tcp", "udp"):
                raise ValueError(f"{location}.proto must be 'tcp' or 'udp'")

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

            comment = action.get("comment", "")

            parsed_actions.append({"action": name, "type": "protoport",
                                  "protocol": protocol, "ports": ports, "comment": comment})
        else:
            raise ValueError(
                f"{location} must be a string or dict, not {type(action)}")

    return parsed_actions


def validate_rule_hostnames(cfg: dict):
    """Validates that all hostnames referenced in firewall rules exist.
    Also ensures that all firewall rules are written with a hostname and not an alias.

    Must be called after all hosts for the site are loaded."""

    routable_vlans = []

    for vswitch in cfg["vswitches"].values():
        for vlan in vswitch["vlans"]:
            if not vlan["routable"]:
                continue

            routable_vlans.append(vlan)

    for host in cfg["hosts"].values():
        # do not add any rules for non infrastructure hosts
        if len(host["roles"]) == 1:  # i.e. only common role
            continue

        actions = [{"action": "allow", "type": "named", "protocol": "ping"}]
        firewall = False

        for role in host["roles"]:
            if role.name == "router":
                firewall = True

        hostname = host["hostname"]
        print("adding host rules for", hostname)

        host_rule = {
            "comment": f"allow access to host {hostname}",
            "ipv4": {"sources": [], "destinations": []},
            "ipv6": {"sources": [], "destinations": []},
            "actions": actions
        }

        # use special firewall destination instead of all interfaces
        if firewall:
            fw = {"vlan": {"name": "firewall", "dhcp_reservations": []}}

            host_rule["ipv4"]["destinations"].append(fw)
            host_rule["ipv6"]["destinations"].append(fw)

            for vlan in routable_vlans:
                source = {"vlan": vlan}

                host_rule["ipv4"]["sources"].append(source)
                host_rule["ipv6"]["sources"].append(source)

            cfg["firewall"]["rules"].append(host_rule)

            host_rule = {
                "comment": f"firewall can ping everything",
                "ipv4": {"sources": [], "destinations": []},
                "ipv6": {"sources": [], "destinations": []},
                "actions": actions
            }
            all = {"vlan": {"name": "all", "dhcp_reservations": []}}
            host_rule["ipv4"]["sources"].append(fw)
            host_rule["ipv6"]["sources"].append(fw)
            host_rule["ipv4"]["destinations"].append(all)
            host_rule["ipv6"]["destinations"].append(all)

            cfg["firewall"]["rules"].append(host_rule)
        else:
            for iface in host["interfaces"]:
                if (iface["type"] not in {"std", "vlan"}) or (not iface["vlan"]["routable"]):
                    continue

                destination = {"vlan": iface["vlan"], "hostname": hostname}

                host_rule["ipv4"]["destinations"].append(destination)
                if iface["ipv6_address"]:
                    host_rule["ipv6"]["destinations"].append(destination)

                for vlan in routable_vlans:
                    if iface["vlan"]["name"] == vlan["name"]:
                        continue  # no need for rule in same vlan

                    source = {"vlan": vlan}

                    host_rule["ipv4"]["sources"].append(source)
                    if iface["ipv6_address"]:
                        host_rule["ipv6"]["sources"].append(source)

            cfg["firewall"]["rules"].append(host_rule)

    for i, rule in enumerate(cfg["firewall"]["rules"], start=1):
        _validate_location_hostname(cfg, rule, i, "ipv4", "sources")
        _validate_location_hostname(cfg, rule, i, "ipv4", "destinations")
        _validate_location_hostname(cfg, rule, i, "ipv6", "sources")
        _validate_location_hostname(cfg, rule, i, "ipv6", "destinations")


def _validate_location_hostname(cfg: dict, rule: dict, idx: int, ip_version: str, src_or_dest: str):
    # allow 'hostname' in firewall rules to be an alias, static hostname mapping or DHCP reserved name
    # determine the real value and map the rule to the actual hostname

    # if the host is defined statically or from DHCP, remove rules without an ip address defined for this version
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

        found = hostname in cfg["hosts"]

        if found:
            _validate_host_vlan(cfg, hostname, vlan, loc_name)
            _logger.debug("%s found '%s' as a top-level host", loc_name, hostname)
            continue
        # else hostname is not a host, check aliases

        for h in cfg["hosts"].values():
            if hostname in h["aliases"]:
                found = True
                hostname = location["hostname"] = h["hostname"]  # update alias to actual hostname
                _logger.debug("%s found '%s' as a top-level host alias for '%s'", loc_name, hostname, h["hostname"])
                break

        if found:
            _validate_host_vlan(cfg, hostname, vlan, loc_name)
            continue
        # else not an alias, check external_hosts

        for ext in cfg["external_hosts"]:
            if hostname in ext["hostnames"]:
                found = True
                if ext[ip_version + "_address"]:
                    _logger.debug("%s found '%s' as an external host", loc_name, hostname)
                else:
                    locations_to_remove.append(i-1)
                    _logger.info("%s found '%s' as a external host without an %s address; removing rule",
                                 loc_name, hostname, ip_version)
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
                f"{loc_name} invalid hostname '{hostname}'; could not find a site-level host or alias, DHCP reservation or static host in vlan '{vlan['name']}', or an external host")

        for vlan_host in vlan["dhcp_reservations"] + vlan["static_hosts"]:
            if (hostname == vlan_host["hostname"]):
                found = True
            elif hostname in vlan_host["aliases"]:
                location["hostname"] = vlan_host["hostname"]  # update alias to actual hostname
                found = True

            if found:
                if vlan_host[ip_version + "_address"]:
                    # reservation address must be in vlan; no need to recheck here
                    _logger.debug("%s found '%s' as an %s DHCP reservation in vlan '%s'",
                                  loc_name, hostname, ip_version, vlan["name"])
                else:
                    locations_to_remove.append(i-1)
                    _logger.debug("%s found '%s' as a DHCP reservation without an %s address; removing rule from vlan '%s'",
                                  loc_name, hostname, ip_version, vlan["name"])
                break

        if not found:
            # if this happens, vlan["known_aliases"] does not line up with the rest of the vlan config
            raise ValueError(
                f"{loc_name} invalid hostname '{hostname}'; could not find a site-level host or alias, DHCP reservation or static host in vlan '{vlan['name']}', or an external host")
    # for locations

    deleted_locations = []

    for location in locations_to_remove:
        deleted_locations.append(rule[ip_version][src_or_dest].pop(location))

    # if there is no src_or_dest, the whole rule is unnecessary
    if not rule[ip_version][src_or_dest]:
        del rule[ip_version]
        _logger.debug(
            f"removing firewall.rule[{idx}] with no valid {src_or_dest} for {ip_version}")


def _validate_host_vlan(cfg: dict, hostname: str, vlan: dict, loc_name: str):
    for iface in cfg["hosts"][hostname]["interfaces"]:
        if iface["vlan"]["name"] == vlan["name"]:
            return

    if vlan["name"] == "firewall":
        for role in cfg["hosts"][hostname]["roles"]:
            if (role.name == "router"):
                return

    raise ValueError(f"{loc_name} invalid host '{hostname}'; it has no interface defined in vlan '{vlan['name']}'")
