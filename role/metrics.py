"""Configuration for server that gathers metrics from other servers in the site."""
from role.roles import Role

import logging

import script.shell as shell

import config.interfaces as interfaces
import config.vlan as vlan

import util.file as file

import script.metrics as metrics

_logger = logging.getLogger(__name__)


class Metrics(Role):
    """Role that adds Grafana and Prometheus based monitoring."""

    def additional_packages(self) -> set[str]:
        return {"grafana", "prometheus"}

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        if site_cfg["site_enable_metrics"]:
            return 1
        else:
            return 0

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        if site_cfg["site_enable_metrics"]:
            return 1
        else:
            return 0

    def additional_configuration(self):
        self.add_alias("metrics")
        self.add_alias("prometheus")
        self.add_alias("grafana")

        if not self._cfg["metrics"]:
            raise ValueError("metrics server must have metrics enabled")

    def validate(self):
        if self._cfg["is_vm"] and (self._cfg["disk_size_mb"] < 1024):
            raise ValueError("metrics server must set 'disk_size_mb' to at least 1,024")

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        file.copy_template(self.name, "grafana.ini", output_dir)
        file.copy_template(self.name, "grafana_confd", output_dir)
        file.copy_template(self.name, "prometheus_datasrc", output_dir)
        file.copy_template(self.name, "prometheus_confd", output_dir)

        # if a preferred vlan to use is specified, find it
        prefer_vlan = self._cfg.get("preferred_metrics_vlan", None)
        preferred_vlan = None

        if prefer_vlan:
            for vswitch in self._cfg["vswitches"].values():
                try:
                    preferred_vlan = vlan.lookup(prefer_vlan, vswitch)["name"]
                    if preferred_vlan:
                        break
                except Exception:
                    pass
            if not preferred_vlan:
                raise ValueError(f"invalid preferred vlan '{prefer_vlan}' for '{self._cfg['hostname']}")

        # determine which ip address prometheus should use to connect to each host for metrics
        # prefer ipv4 addresses on the same vlan
        hosts_to_ips = {}
        for host_cfg in self._cfg["hosts"].values():
            if not host_cfg["metrics"]:
                continue

            preferred = other = None

            for match in interfaces.find_ips_to_interfaces(self._cfg, host_cfg["interfaces"], first_match_only=False):
                if match["dest_iface"]["vlan"]["name"] == preferred_vlan:
                    preferred = str(match["ipv4_address"])
                else:
                    other = str(match["ipv4_address"])

            if preferred:
                hosts_to_ips[host_cfg["hostname"]] = preferred
            elif other:
                hosts_to_ips[host_cfg["hostname"]] = other
            else:
                _logger.warning(f"no matching ip address found to '{host_cfg['hostname']}';"
                                " no metrics will be collected")

        prometheus = file.load_yaml("templates/metrics/prometheus.yml")

        # for each metric type, add a scrape_config with all the hosts that have that exporter enabled
        for metric_type, ports in metrics.get_types_and_ports().items():
            targets = []
            relabel_configs = []
            exporter = {"job_name": metric_type,
                        "static_configs": [{"targets": targets}],
                        "relabel_configs": relabel_configs}

            for hostname, ip in hosts_to_ips.items():
                if not self._cfg["hosts"][hostname]["metrics"][metric_type]["enabled"]:
                    continue

                # multiple ports => target each
                if isinstance(ports, int):
                    targets.append(f"{ip}:{ports}")
                elif isinstance(ports, list):
                    for port in ports:
                        targets.append(f"{ip}:{port}")
                else:
                    raise ValueError(f"ports for {metric_type} was {type(ports)} not int or list")

                # always relabel with the hostname
                relabel_configs.append({
                    "source_labels": ["__address__"],
                    "regex": ip + ":.*",
                    "target_label": "instance",
                    "replacement": hostname
                })

            prometheus["scrape_configs"].append(exporter)

        file.write("prometheus.yml", file.output_yaml(prometheus), output_dir)

        setup.append(
            "install -o grafana -g grafana -m 600 $DIR/prometheus_datasrc /var/lib/grafana/provisioning/datasources/prometheus.yaml")
        setup.append("root install $DIR/grafana.ini /etc")
        setup.append("root install $DIR/prometheus.yml /etc/prometheus")
        setup.append("root install $DIR/grafana_confd /etc/conf.d/grafana")
        setup.append("root install $DIR/prometheus_confd /etc/conf.d/prometheus")
        setup.blank()

        setup.comment("remove warning in log output")
        setup.append("mkdir /var/lib/grafana/plugins")
        setup.append("chown grafana:grafana /var/lib/grafana/plugins")
        setup.blank()

        setup.service("grafana")
        setup.service("prometheus")

        setup.append(
            "echo m3trics! > grafana-cli -config /etc/grafana.ini -homepath /usr/share/grafana admin reset-admin-password --password-from-stdin")


# mkdir /var/log/grafana
# chown grafana:grafana /var/log/grafana
