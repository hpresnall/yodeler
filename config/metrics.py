"""Handles parsing and validating metrics configuration from host YAML files."""
import logging
import copy
from util import parse

_logger = logging.getLogger(__name__)


def validate(cfg: dict):
    """Ensure metrics are configured correctly, if required."""
    metrics = copy.deepcopy(_DEFAULT_METRICS_CONFIG)

    # site disabled => ignore host's enable_metrics setting
    if not cfg["site_enable_metrics"] or not cfg["enable_metrics"]:
        for metric in metrics.values():
            metric["enabled"] = False

        # overwrite existing config
        cfg["metrics"] = metrics

        return

    # enabled by default on physical servers
    metrics["nvme"]["enabled"] = not cfg["is_vm"]
    metrics["ipmi"]["enabled"] = not cfg["is_vm"]

    # enabled by default on systems with real disks
    needs_smartmon = not cfg["is_vm"]

    for disk in cfg["disks"]:
        if disk["type"] != "img":  # device or passthrough
            needs_smartmon = True
            break

    metrics["smartmon"]["enabled"] = needs_smartmon

    # enable collectors for roles only if metrics are enabled ...

    for role in cfg["roles"]:
        if role.name == "vmhost":
            metrics["libvirt"]["enabled"] = True
        if role.name == "dns":
            metrics["pdns"]["enabled"] = True

    # ipmi & smartmon packages are in the Alpine testing repo
    if metrics["ipmi"]["enabled"]:
        if cfg["is_vm"]:
            raise ValueError(f"{cfg['hostname']}: cannot enable IPMI metrics on VMs")

        cfg["enable_testing_repository"] = True
    if metrics["smartmon"]["enabled"]:
        cfg["enable_testing_repository"] = True

    _update_from_host(metrics, cfg)

    cfg["metrics"] = metrics

    _logger.debug(f"metrics for '{cfg['hostname']}': {metrics}")


def _update_from_host(metrics: dict, cfg: dict):
    if not "metrics" in cfg:
        return

    hostname = cfg["hostname"]
    cfg_metrics = parse.get_dict(hostname, "metrics", cfg)

    for metric_type, metric in cfg_metrics.items():
        location = f"{hostname}.metrics['{metric_type}']"

        # metric_type must be a valid string
        parse.non_empty_string(location, metric_type)

        if not metric_type in metrics:
            raise KeyError(f"{location} is not a valid metric type")

        # allow just setting interval or enabled as a shortcut
        # e.g 'node: 10' instead of 'node: { "interval": 10 }'
        if type(metric) is int:
            metric = {"interval": metric}
        elif isinstance(metric, bool):
            metric = {"enabled": metric}
        else:
            parse.non_empty_dict(location, metric)

        if "interval" in metric:
            # interval set; ensure valid int
            interval = parse.get_int(location, "interval", metric)

            if interval < 1:
                raise ValueError(f"{location} interval must be greater than 0")

            metrics[metric_type]["interval"] = interval

            # assume enabled unless explicitly set to false
            # allows just setting the interval
            metrics[metric_type]["enabled"] = parse.set_bool_default(location, "enabled", metric, True)
        elif "enabled" in metric:
            # no need to update interval
            # use the default enabled if not set
            metrics[metric_type]["enabled"] = parse.set_bool_default(
                location, "enabled", metric, metrics[metric_type]["enabled"])


def additional_packages(cfg: dict) -> set[str]:
    """Add additional packages for metrics."""
    if not cfg["metrics"]:
        return set()

    metrics = cfg["metrics"]

    packages = {"prometheus-node-exporter"}

    if metrics["libvirt"]["enabled"]:
        packages.add("prometheus-libvirt-exporter")
    if metrics["nvme"]["enabled"]:
        packages.add("nvme-cli")
    if metrics["onewire"]["enabled"]:
        packages.add("owfs")
    if metrics["ipmi"]["enabled"]:
        packages.add("prometheus-ipmi-exporter")
    if metrics["smartmon"]["enabled"]:
        packages.add("prometheus-smartctl-exporter")

    return packages


# all times in seconds
# note slower default times in seconds for scraping some metric types
_DEFAULT_METRICS_CONFIG = {
    "node": {
        "enabled": True,
        "interval": 15
    },
    "libvirt": {
        "enabled": False,
        "interval": 60
    },
    "pdns": {
        "enabled": False,
        "interval": 15
    },
    "nvme": {
        "enabled": False,
        "interval": 60
    },
    "ipmi": {
        "enabled": False,
        "interval": 30,
    },
    "smartmon": {
        "enabled": False,
        "interval": 60
    },
    "onewire": {
        "enabled": False,
        "interval": 60
    }
}
