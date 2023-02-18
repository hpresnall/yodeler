"""Utility for awall configuration."""
import logging
import os

import util.file
import util.shell

from roles.role import Role

_logger = logging.getLogger(__name__)


def configure(interfaces: list[dict], roles: list[Role], setup: util.shell.ShellScript, output_dir: str):
    """Create awall configuration for the given interfaces.
    Outputs all JSON to <output_dir>/awall.
    Returns a shell script fragment to process the JSON files and create iptables rules."""
    # create all JSON config from template
    # see https://wiki.alpinelinux.org/wiki/Zero-To-Awall

    # load all template services
    # roles can add or overwrite common templates
    services = {'custom': {}}
    for role in roles:
        _load_templates(services, "templates/" + role.name + "/awall")

    # remove custom services and handle separately
    custom_services = {'service': services.pop('custom', None)}

    # base json template; add a zone and policy for each interface
    base = {"description": "base zones and policies", "zone": {}, "policy": []}

    for iface in interfaces:
        if iface["type"] != "std":
            continue

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

    util.file.write("base.json", util.file.output_json(base), awall)
    util.file.write("custom-services.json", util.file.output_json(custom_services), awall)

    setup.append("log \"Configuring awall\"")
    setup.append("rootinstall $DIR/awall/base.json /etc/awall/private")
    setup.append("rootinstall $DIR/awall/custom-services.json /etc/awall/private")

    for name, service in services.items():
        util.file.write(name, util.file.output_json(service), awall)

        setup.append(f"rootinstall $DIR/awall/{name} /etc/awall/optional")
        setup.append("awall enable {}".format(name[:-5]))  # name without .json

    setup.blank()
    setup.append("# create iptables rules and apply at boot")
    setup.append("awall translate -o /tmp")
    setup.append("rm -f /etc/iptables/*")
    setup.append("rootinstall /tmp/rules-save /tmp/rules6-save /etc/iptables")

    setup.service("iptables", "boot")
    setup.service("ip6tables", "boot")


def _load_templates(services: dict, template_dir: str):
    if not os.path.exists(template_dir):
        return

    for path in os.listdir(template_dir):
        service = util.file.load_json(os.path.join(template_dir, path))

        if os.path.isdir(path):
            continue

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
