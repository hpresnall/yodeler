"""Handles parsing and validating metrics configuration from host YAML files."""


def validate(cfg: dict):
    """Ensure metrics are configured correctly, if required."""
    enable_metrics = True
    # ignore host's enable_metrics setting
    if not cfg["site_enable_metrics"]:
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

    # enabled by default
    _validate_type(hostname, metrics, "node", True)

    # enabled by default on physical servers
    _validate_type(hostname, metrics, "nvme", not cfg["is_vm"])

    # disabled by default
    _validate_type(hostname, metrics, "onewire", False)
    _validate_type(hostname, metrics, "ipmi", False)

    # enable collectors for roles only if metrics are enabled ...
    for role in cfg["roles"]:
        if role.name == "vmhost":
            _validate_type(hostname, metrics, "libvirt", True)
        if role.name == "dns":
            _validate_type(hostname, metrics, "pdns", True)

    # but, ensure existence regardless
    metrics.setdefault("libvirt", {"enabled": False})
    metrics.setdefault("pdns", {"enabled": False})

    # ipmi needs to build the collector see script/metrics.py
    if metrics["ipmi"]["enabled"]:
        cfg["needs_site_build"] = True


def _validate_type(hostname: str, metrics: dict, type: str, enabled: bool):
    if type in metrics:
        location = f"{hostname}.metrics['{type}']"

        metric_cfg = metrics[type]
        if not isinstance(metric_cfg, dict):
            raise ValueError(f"{location} must be a dict")

        value = metric_cfg.setdefault("enabled", enabled)
        if not isinstance(value, bool):
            raise ValueError(f"{location}.enabled must be a boolean")
    else:
        metrics[type] = {"enabled": enabled}


def add_packages(cfg: dict):
    """Add additional packages for metrics."""
    if not cfg["metrics"]:
        return

    cfg["packages"].add("prometheus-node-exporter")

    if cfg["metrics"]["libvirt"]["enabled"]:
        cfg["packages"].add("prometheus-libvirt-exporter")
    if cfg["metrics"]["nvme"]["enabled"]:
        cfg["packages"].add("nvme-cli")
    if cfg["metrics"]["onewire"]["enabled"]:
        cfg["packages"].add("owfs")
