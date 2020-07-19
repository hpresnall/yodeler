import os
import json

import util.file


def configure(interfaces, dir, before_install=True):
    # create all JSON config from template
    # see https://wiki.alpinelinux.org/wiki/Zero-To-Awall

    # base json template; add a zone and policy for each interface
    base = {"description": "base zones and policies", "zone": {}, "policy": []}

    # load all template services
    services = {}
    for path in os.listdir("templates/awall"):
        with open(os.path.join("templates/awall", path)) as f:
            service = json.load(f)
        # assume service has a single filter and it is for input
        service["filter"][0]["in"] = []
        services[path] = service

    for iface in interfaces:
        zone = iface["firewall_zone"]
        name = iface["name"]

        # add zones for each interface
        base["zone"][zone] = {"iface": name}
        # allow all traffic out
        # allow no traffic in, except as configured by servics
        base["policy"].append({"out": zone, "action": "accept"})
        base["policy"].append({"in": zone, "action": "drop"})

        # all zones can retrieve traffic for all services
        for service in services.values():
            service["filter"][0]["in"].append(zone)

    # write JSON config to awall subdirectory
    awall = os.path.join(dir, "awall")
    os.mkdir(awall)

    b = ["# configure awall"]
    b.append("rootinstall $DIR/awall/base.json /etc/awall/optional")

    # after install, only base will change due to different interfaces
    if before_install:
        b.append("awall enable base")

    util.file.write("base.json",  json.dumps(base, indent=2), awall)

    for name, service in services.items():
        util.file.write(name, json.dumps(service, indent=2), awall)

        # after_intall, services are already enabled
        if before_install:
            b.append(f"rootinstall $DIR/awall/{name} /etc/awall/optional")
            b.append("awall enable {}".format(name[:-5]))  # name without .json

    b.append("")
    b.append("# create iptables rules and apply at boot")
    b.append("awall translate -o /tmp")
    b.append("rootinstall /tmp/rules-save /tmp/rules6-save /etc/iptables")

    if before_install:
        b.append("rc-update add iptables boot")
        b.append("rc-update add ip6tables boot")

    return "\n".join(b)
