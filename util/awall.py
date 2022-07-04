"""Utility for awall configuration."""
import logging
import os
import json

import util.file

_logger = logging.getLogger(__name__)


def configure(interfaces, roles, output_dir):
    """Create awall configuration for the given interfaces.
    Outputs all JSON to <output_dir>/awall.
    Returns a shell script fragment to process the JSON files and create iptables rules."""
    # create all JSON config from template
    # see https://wiki.alpinelinux.org/wiki/Zero-To-Awall

    # load all template services
    # roles can add or overwrite common templates
    services = {'custom': {}}
    _load_templates(services, "templates/common/awall")
    for role in roles:
        _load_templates(services, "templates/" + role.name + "/awall")

    # remove custom services and handle separately
    custom_services = {'service': services.pop('custom', None)}

    # base json template; add a zone and policy for each interface
    base = {"description": "base zones and policies", "zone": {}, "policy": []}

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

    # main service just imports base and custom-services
    services["main.json"] = {"import": ["base", "custom-services"]}

    # write JSON config to awall subdirectory
    awall = os.path.join(output_dir, "awall")
    os.mkdir(awall)

    util.file.write("base.json", json.dumps(base, indent=2), awall)
    util.file.write("custom-services.json",
                    json.dumps(custom_services, indent=2), awall)

    buffer = ["echo \"Configuring awall\""]
    buffer.append("rootinstall $DIR/awall/base.json /etc/awall/private")
    buffer.append(
        "rootinstall $DIR/awall/custom-services.json /etc/awall/private")

    for name, service in services.items():
        util.file.write(name, json.dumps(service, indent=2), awall)

        buffer.append(f"rootinstall $DIR/awall/{name} /etc/awall/optional")
        buffer.append("awall enable {}".format(
            name[:-5]))  # name without .json

    buffer.append("")
    buffer.append("# create iptables rules and apply at boot")
    buffer.append("awall translate -o /tmp")
    buffer.append("rm -f /etc/iptables/*")
    buffer.append("rootinstall /tmp/rules-save /tmp/rules6-save /etc/iptables")

    buffer.append("rc-update add iptables boot")
    buffer.append("rc-update add ip6tables boot")

    return "\n".join(buffer)


def _load_templates(services, template_dir):
    if not os.path.exists(template_dir):
        return

    for path in os.listdir(template_dir):
        with open(os.path.join(template_dir, path)) as template:
            service = json.load(template)

        if path == "custom-services.json":
            # consolidate custom service definitions into a single entry
            if "service" in service and service["service"]:
                for name, definition in service["service"].items():
                    services["custom"][name] = definition
            else:
                _logger.warning("'%s' does not contain any services",
                                os.path.join(template_dir, path))
        else:
            # assume service has a single filter and it is for input
            # remove existing interfaces and recreate it using config
            service["filter"][0]["in"] = []
            services[path] = service
