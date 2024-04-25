"""Utility for awall configuration."""
from role.roles import Role

import logging
import os

import util.file as file

import script.shell as shell
import script.metrics as metrics

_logger = logging.getLogger(__name__)


def configure(cfg: dict, setup: shell.ShellScript, output_dir: str):
    """Create awall configuration for the given interfaces.
    Outputs all JSON to <output_dir>/awall.
    Returns a shell script fragment to process the JSON files and create iptables rules."""
    # create all JSON config from template
    # see https://wiki.alpinelinux.org/wiki/Zero-To-Awall
    if not cfg["local_firewall"]:
        return

    # main service just imports base and custom-services
    # custom services will be put in a special entry and removed for separate handling
    services = {
        "main.json": {"import": ["base", "custom-services"]},
        "custom": {}}

    # load all template services
    # roles can add or overwrite common templates
    for role in cfg["roles"]:
        _load_templates(services, "templates/" + role.name + "/awall")

    custom_services = {'service': services.pop('custom', {})}

    for metric_type, metric in cfg["metrics"].items():
        if metric["enabled"]:
            _add_service_for_metric(metric_type, services, custom_services)

    # base json template; add a zone and policy for each interface
    base = {"description": "base zones and policies", "zone": {}, "policy": []}

    for iface in cfg["interfaces"]:
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
        for name, service in services.items():
            if name == "main.json":
                continue

            for filter in service["filter"]:
                filter["in"].append(zone)

    # write JSON config to awall subdirectory
    awall = os.path.join(output_dir, "awall")
    os.mkdir(awall)

    setup.log("Configuring awall")
    setup.append("rootinstall $DIR/awall/base.json /etc/awall/private")
    setup.append("rootinstall $DIR/awall/custom-services.json /etc/awall/private")

    for name, service in services.items():
        service_name = name[:-5]  # name without .json

        # if the service is disabled, remove it from custom services & do not output the service file
        if (service_name != "main") and (service_name in cfg["awall_disable"]):
            if service_name in custom_services["service"]:
                del custom_services["service"][service_name]
            continue

        file.write(name, file.output_json(service), awall)

        setup.append(f"rootinstall $DIR/awall/{name} /etc/awall/optional")
        setup.append(f"awall enable {service_name}")

    setup.blank()
    setup.append("# create iptables rules and apply at boot")
    setup.append("awall translate -o /tmp")
    setup.append("rm -f /etc/iptables/*")
    setup.append("rootinstall /tmp/rules-save /tmp/rules6-save /etc/iptables")

    setup.service("iptables", "boot")
    setup.service("ip6tables", "boot")
    setup.blank()

    file.write("base.json", file.output_json(base), awall)
    file.write("custom-services.json", file.output_json(custom_services), awall)


def _load_templates(services: dict, template_dir: str):
    if not os.path.exists(template_dir):
        return

    for path in os.listdir(template_dir):
        if os.path.isdir(path):
            continue

        service = file.load_json(os.path.join(template_dir, path))

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


def _add_service_for_metric(metric_type: str, services: dict, custom_services: dict):
    # create the service and the custom definition for each metric exporter
    service_name = metric_type + "-exporter"

    custom_services["service"][service_name] = {
        "proto": "tcp",
        "port": metrics.get_ports(metric_type)
    }

    services[service_name + ".json"] = {
        "description": "allow Prometheus metrics for " + metric_type,
        "filter": [
            {"in": [],
                "service": service_name,
                "action": "accept"
             }
        ]
    }
