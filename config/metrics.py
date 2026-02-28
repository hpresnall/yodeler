"""Handles parsing and validating metrics configuration from host YAML files."""
import logging

from util import parse

_logger = logging.getLogger(__name__)


def validate(cfg: dict):
    """Ensure metrics are configured correctly, if required."""
    enable_metrics = True

    if not cfg["site_enable_metrics"]:
        # ignore host's enable_metrics setting
        enable_metrics = False
    elif not cfg["enable_metrics"]:
        # metrics disabled for the host
        enable_metrics = False

    if not enable_metrics:
        cfg["metrics"] = {}
        return

    metrics = cfg["metrics"] = cfg.get("metrics", {})
    hostname = cfg["hostname"]

    if not isinstance(metrics, dict):
        raise ValueError(f"metrics config must be a dict for '{hostname}'")

    # note slower default times in seconds for scraping some metric types

    # enabled by default
    _validate(hostname, metrics, "node", True, 15)

    # enabled by default on physical servers
    _validate(hostname, metrics, "nvme", not cfg["is_vm"], 60)
    _validate(hostname, metrics, "ipmi", not cfg["is_vm"], 30)

    # enabled by default on systems with real disks
    needs_smartmon = not cfg["is_vm"]

    for disk in cfg["disks"]:
        if disk["type"] != "img":  # device or passthrough
            needs_smartmon |= True
            break

    _validate(hostname, metrics, "smartmon", needs_smartmon, 60)

    # disabled by default
    _validate(hostname, metrics, "onewire", False, 60)

    # enable collectors for roles only if metrics are enabled ...
    libvirt = pdns = False

    for role in cfg["roles"]:
        if role.name == "vmhost":
            libvirt = True
        if role.name == "dns":
            pdns = True

    _validate(hostname, metrics, "libvirt", libvirt, 15)
    _validate(hostname, metrics, "pdns", pdns, 15)

    # ipmi & smartmon are in the Alpine testing repo
    if metrics["ipmi"]["enabled"]:
        if cfg["is_vm"]:
            raise ValueError(f"{cfg['hostname']}: cannot enable IPMI metrics on VMs")

        cfg["enable_testing_repository"] = True
    if metrics["smartmon"]["enabled"]:
        cfg["enable_testing_repository"] = True

    _logger.debug(f"metrics for '{cfg['hostname']}': {metrics}")


def _validate(hostname: str, metrics: dict, type: str, default_enabled: bool, default_interval: int):
    if type in metrics:
        location = f"{hostname}.metrics['{type}']"
        metric_cfg = parse.non_empty_dict(location, metrics[type])
    else:
        metrics[type] = {
            "enabled": default_enabled,
            "interval": default_interval
        }
        return

    # default to enabled if setting an interval
    if "interval" in metric_cfg:
        default_enabled = True

    enabled = parse.set_default_bool("enabled", metric_cfg, default_enabled)
    interval = parse.set_default_int("interval", metric_cfg, default_interval)

    metrics[type] = {
        "enabled": enabled,
        "interval": interval
    }


def add_packages(cfg: dict):
    """Add additional packages for metrics."""
    if not cfg["metrics"]:
        return

    metrics = cfg["metrics"]

    cfg["packages"].add("prometheus-node-exporter")

    if metrics["libvirt"]["enabled"]:
        cfg["packages"].add("prometheus-libvirt-exporter")
    if metrics["nvme"]["enabled"]:
        cfg["packages"].add("nvme-cli")
    if metrics["onewire"]["enabled"]:
        cfg["packages"].add("owfs")
    if metrics["ipmi"]["enabled"]:
        cfg["packages"].add("prometheus-ipmi-exporter")
    if metrics["smartmon"]["enabled"]:
        cfg["packages"].add("prometheus-smartctl-exporter")
