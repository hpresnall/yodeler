"""Utility for awall configuration."""
import os
import json

import util.file


def configure(interfaces, roles, output_dir, before_install=True):
    """Create awall configuration for the given interfaces.
    Outputs all JSON to <output_dir>/awall.
    Returns a shell script fragment to process the JSON files and create iptables rules."""
    # create all JSON config from template
    # see https://wiki.alpinelinux.org/wiki/Zero-To-Awall

    # base json template; add a zone and policy for each interface
    base = {"description": "base zones and policies", "zone": {}, "policy": []}

    # load all template services
    services = {}
    _load_dir(services, "templates/awall")
    for role in roles:
        _load_dir(services, "templates/" + role.name + "/awall")

    for iface in interfaces:
        zone = iface["firewall_zone"]
        name = iface["name"]

        # add zones for each interface
        base["zone"][zone] = {"iface": name}
        # allow all traffic out
        # allow no traffic in, except as configured by servics
        base["policy"].append({"out": zone, "action": "accept"})
        base["policy"].append({"in": zone, "action": "drop"})

        # all zones can recieve traffic for all services
        for service in services.values():
            service["filter"][0]["in"].append(zone)

    # write JSON config to awall subdirectory
    awall = os.path.join(output_dir, "awall")
    os.mkdir(awall)

    buffer = ["# configure awall"]
    buffer.append("rootinstall $DIR/awall/base.json /etc/awall/optional")

    # after install, assume enable not needed
    if before_install:
        buffer.append("awall enable base")

    util.file.write("base.json", json.dumps(base, indent=2), awall)

    for name, service in services.items():
        util.file.write(name, json.dumps(service, indent=2), awall)

        buffer.append(f"rootinstall $DIR/awall/{name} /etc/awall/optional")

        # after_install, services are already enabled
        if before_install:
            buffer.append("awall enable {}".format(name[:-5]))  # name without .json

    buffer.append("")
    buffer.append("# create iptables rules and apply at boot")
    buffer.append("awall translate -o /tmp")
    buffer.append("rm /etc/iptables/*")
    buffer.append("rootinstall /tmp/rules-save /tmp/rules6-save /etc/iptables")

    if before_install:
        buffer.append("rc-update add iptables boot")
        buffer.append("rc-update add ip6tables boot")

    return "\n".join(buffer)


def _load_dir(services, template_dir):
    if not os.path.exists(template_dir):
        return

    for path in os.listdir(template_dir):
        with open(os.path.join(template_dir, path)) as template:
            service = json.load(template)
        # assume service has a single filter and it is for input
        service["filter"][0]["in"] = []
        services[path] = service
