"""Configuration for server that gathers Prometheus metrics from other hosts in the site."""
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
        return {"grafana", "prometheus", "jq"}

    def additional_aliases(self) -> list[str]:
        return ["metrics", "prometheus", "grafana"]

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
        if not self._cfg["metrics"]:
            raise ValueError("metrics server must have metrics enabled")

        self._cfg.setdefault("grafana_password", "m3trics!")

        # slower default times in seconds for scraping some metric types
        metric_intervals = self._cfg.get("metric_intervals", {})
        metric_intervals.setdefault("default", 15)
        metric_intervals.setdefault("nvme", 60)
        metric_intervals.setdefault("onewire", 60)
        metric_intervals.setdefault("ipmi", 30)

        self._cfg["metric_intervals"] = metric_intervals

        if self._cfg["backup"]:
            self._cfg["backup_script"].comment("backup Prometheus DB")
            self._cfg["backup_script"].append("snapshot=/var/lib/prometheus/data/snapshots/$(curl -s -XPOST http://localhost:9090/api/v1/admin/tsdb/snapshot | jq -r .data.name)")
            self._cfg["backup_script"].append("tar cfz /backup/prometheus_backup.tar.gz $snapshot")
            self._cfg["backup_script"].append("rm -rf $snapshot")

    def validate(self):
        if self._cfg["is_vm"] and (self._cfg["disk_size_mb"] < 1024):
            raise ValueError("metrics server must set 'disk_size_mb' to at least 1,024")

        for metric, interval in self._cfg["metric_intervals"].items():
            if not isinstance(interval, int):
                raise ValueError(f"{self._cfg['hostname']}.metric_intervals['{metric}']={interval} must be an integer")

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

        # base prometheus config; scrape configs will be added for each metric collector
        prometheus = {
            "global": {"scrape_interval": self._cfg["metric_intervals"]["default"]},
            "scrape_configs": [
                {
                    "job_name": "prometheus",
                    "comment": "prometheus itself",
                    "static_configs": [{"targets": ["localhost:9090"]}]
                }
            ]
        }

        # for each metric type, add a scrape_config with all the hosts that have that exporter enabled
        for metric_type, ports in metrics.get_types_and_ports().items():
            targets = []
            relabel_configs = []
            exporter = {"job_name": metric_type,
                        "static_configs": [{"targets": targets}],
                        "relabel_configs": relabel_configs}

            interval = self._cfg["metric_intervals"].get(metric_type)
            if interval:
                exporter["scrape_interval"] = interval

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

        # order matters; properf configuration is needed to provision grafana and create /var/lib/grafana
        setup.comment("add grafana and prometheus config")
        setup.append("rootinstall $DIR/grafana.ini /etc")
        setup.append("rootinstall $DIR/prometheus.yml /etc/prometheus")
        setup.append("rootinstall $DIR/grafana_confd /etc/conf.d")
        setup.append("rootinstall $DIR/prometheus_confd /etc/conf.d")
        setup.append("mv /etc/conf.d/grafana_confd /etc/conf.d/grafana")
        setup.append("mv /etc/conf.d/prometheus_confd /etc/conf.d/prometheus")
        setup.blank()

        setup.comment("create grafana config with a prometheus datasource")
        setup.append("mkdir -p /var/lib/grafana/data /var/lib/grafana/plugins /var/lib/grafana/provisioning /var/log/grafana")
        setup.append("cd /var/lib/grafana/provisioning")
        setup.append("mkdir alerting dashboards datasources notifiers plugins")
        setup.append("cd -")
        setup.append(
            "install -o grafana -g grafana -m 600 $DIR/prometheus_datasrc /var/lib/grafana/provisioning/datasources")
        setup.append(
            "mv /var/lib/grafana/provisioning/datasources/prometheus_datasrc /var/lib/grafana/provisioning/datasources/prometheus.yaml")
        setup.append("chown -R grafana:grafana /var/lib/grafana")
        setup.blank()

        setup.comment("provision grafana")
        setup.append(
            f"echo \"{self._cfg['grafana_password']}\" > grafana-cli -config /etc/grafana.ini -homepath /usr/share/grafana admin reset-admin-password --password-from-stdin")
        setup.blank()

        setup.service("grafana")
        setup.service("prometheus")

        if self._cfg["backup"]:
            setup.blank()
            setup.comment("restore Prometheus DB")
            setup.append("if [ -f $BACKUP/prometheus_backup.tar.gz ]; then")
            setup.append("  cd /var/lib/prometheus/data")
            setup.append("  tar xvz $BACKUP/prometheus_backup.tar.gz")
            setup.append("fi")

# mkdir /var/log/grafana
# chown grafana:grafana /var/log/grafana
