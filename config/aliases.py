import role.roles as roles

import util.dns as dns
import util.parse as parse


def configure(cfg: dict):
    hostname = cfg["hostname"]

    # allow both 'alias' and 'aliases'; only store 'aliases'
    aliases = parse.read_string_list_plurals({"alias", "aliases"}, cfg, "alias for " + cfg["hostname"])
    cfg.pop("alias", None)

    # final set of aliases is all defined values plus role names & role aliases
    cfg["aliases"] = set()

    for alias in aliases:
        if dns.invalid_hostname(alias):
            raise ValueError(f"invalid alias '{alias}' for host '{hostname}'")
        cfg["aliases"].add(alias.lower())

    # ensure hostname is not duplicated by an alias
    cfg["aliases"].discard(cfg["hostname"])


def make_unique(cfg: dict, role: roles.Role):
    """Add unique role-based aliases to the host.
    The aliases will be numbered if other hosts in the site have the same role.
    Note this does not check for non-role aliases defined in the host; validate() will ensure those are not duplicated."""
    _make_unique(cfg, role.name, role.name)

    for alias in role.additional_aliases():
        _make_unique(cfg, role.name, alias)


def _make_unique(cfg: dict, role: str, alias: str):
    # allow hostname to be the same, but do not add as an alias
    # site-level validation will ensure uniqueness of all hosts / aliases
    if cfg["hostname"] == alias:
        return

    # add to this host's config; may be replaced below
    cfg["aliases"].add(alias)

    existing_hosts = cfg["roles_to_hostnames"][role]

    # only instance of the role, do not rename
    if len(existing_hosts) == 1:
        return

    # rename all aliases by renumbering
    for i, host in enumerate(existing_hosts, start=1):
        aliases = cfg["hosts"][host]["aliases"]
        aliases.discard(alias)
        aliases.add(alias + str(i))


def validate(cfg: dict):
    """Check all aliases for duplicates against the firewall's 'static_hosts' and any DHCP reservations in connected
    vlan's. Does not check against all aliases in the site since all hosts may not have been defined."""
    hostname = cfg["hostname"]

    for alias in cfg["aliases"]:
        if alias in cfg["firewall"]["static_hosts"]:
            raise ValueError(f"alias '{alias}' for host '{hostname}' is already used in firewall.static_hosts")

        # ensure no clashes with other hosts
        for other_hostname, other_host in cfg["hosts"].items():
            if other_hostname == hostname:
                # site.py already checked for duplicate hostnames => must be this host
                continue
            if alias in other_host["aliases"]:
                raise ValueError(
                    f"alias '{alias}' for host '{hostname}' is already used as an alias for '{other_hostname}'")

    # ensure no clashes with DHCP reservations
    aliases = set(cfg["aliases"])
    aliases.add(cfg["hostname"])

    for iface in cfg["interfaces"]:
        if iface["type"] not in {"std", "vlan"}:
            continue

        vlan = iface["vlan"]["name"]
        vlan_aliases = iface["vlan"]["known_aliases"]

        if not aliases.isdisjoint(vlan_aliases):
            raise ValueError(
                f"vlan '{vlan}' contains DHCP reservations {aliases.intersection(vlan_aliases)} that conflict with a global hostname or alias")
