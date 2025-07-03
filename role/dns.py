"""Configuration & setup for a PowerDNS server."""
from role.roles import Role

import util.file as file
import util.address as address

import script.shell as shell
import script.sysctl as sysctl

import config.interfaces as interfaces
import config.firewall as fw


class Dns(Role):
    """DNS defines the configuration needed to setup PowerDNS. Configures both the DNS server and a recursor to
    handle internal and external DNS."""

    def additional_packages(self):
        return {"pdns", "pdns-recursor", "pdns-backend-sqlite3", "pdns-doc", "pdns-openrc", "bind-tools"}

    def additional_configuration(self):
        # allow all routable vlans DNS access to this host on all its interfaces
        hostname = self._cfg["hostname"]
        destinations = fw.destinations_from_interfaces(self._cfg["interfaces"], hostname)

        if destinations:
            actions = [
                fw.allow_service("dns"),
                fw.allow_proto_port(553),
                fw.allow_proto_port(553, proto="udp")
            ]

            fw.add_rule(self._cfg, [fw.location_all()], destinations, actions, f"DNS and nsupdate for {hostname}")

        if self._cfg["backup"]:
            self._cfg["backup_script"].comment("backup PDNS database")
            self._cfg["backup_script"].append(
                f"sqlite3 -readonly /var/lib/pdns/pdns.sqlite3 \".backup {self._cfg['backup_dir']}/pdns.bak\"")
            self._cfg["backup_script"].blank()

    def validate(self):
        if len(self._cfg["external_dns"]) == 0:
            raise KeyError("cannot configure DNS server with no external_dns addresses defined")

        domain = self._cfg["domain"]
        if not domain:
            domain = self._cfg["primary_domain"]
            if not domain:
                raise KeyError(("cannot configure DNS server with no primary_domain or top-level site domain"))
        self._cfg["dns_domain"] = domain
        # note, no top-level domain => vlans will not have domains and DNS will only have the single, top-level zone

        for iface in self._cfg["interfaces"]:
            if (iface["type"] == "std") and (iface["ipv4_address"] == "dhcp"):
                raise KeyError(
                    f"host '{self._cfg['hostname']}' cannot configure a DNS server with a DHCP address on interface '{iface['name']}'")

        missing_vlans = interfaces.check_accessiblity(self._cfg["interfaces"],
                                                      self._cfg["vswitches"].values())

        if missing_vlans:
            raise ValueError(
                f"host '{self._cfg['hostname']}' does not have access to vlans {missing_vlans} to provide DNS")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        # fake isp runs its own dns
        return 0 if 'fakeisp' in site_cfg["roles_to_hostnames"] else 1

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return 2  # no need for additional redundancy

    def needs_build_image(self) -> bool:
        return True

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        """Create the scripts and configuration files for the given host's configuration."""
        sysctl.enable_tcp_fastopen(setup, output_dir)

        # scripts for creating the blackhole file
        file.copy_template("dns", "build_recursor_lua.sh", output_dir)
        file.copy_template("dns", "create_lua_blackhole.py", output_dir)

        build_blackhole = file.substitute("dns", "build_blackhole.sh", self._cfg)
        if self._cfg["is_vm"]:
            self._cfg["before_chroot"].append(build_blackhole)
            setup.comment("blackhole script created before chroot in vmhost's build image")
        else:
            setup.append(build_blackhole)
        setup.blank()

        setup.append(f"install -o pdns -g pdns -m 600 $DIR/pdns.conf /etc/pdns")
        setup.append(f"install -o recursor -g recursor -m 600 $DIR/recursor.yml /etc/pdns")
        setup.append(f"install -o recursor -g recursor -m 600 /tmp/blackhole.lua /etc/pdns")
        setup.blank()

        setup.comment("ensure startup does not log to the console")
        setup.append("sed -i -e \"s#\\${daemon}#\\${daemon} 2>&1 > /dev/null#g\" /etc/init.d/pdns-recursor")
        setup.blank()

        setup.service("pdns")
        setup.service("pdns-recursor")
        setup.blank()

        if self._cfg["backup"]:
            setup.comment(
                "not restoring PDNS database from backups to avoid calculating config diffs or adding duplicate records")
            setup.comment("let dynamic DNS re-add DHCP records as they are requested")
            setup.blank()

        setup.comment("create SQLite DB")
        setup.append("mkdir /var/lib/pdns")
        setup.append("sqlite3 /var/lib/pdns/pdns.sqlite3 < /usr/share/doc/pdns/schema.sqlite3.sql")
        setup.append("chown -R pdns:pdns /var/lib/pdns")
        setup.blank()

        dns_domain = self._cfg["dns_domain"]
        dns_server = "dns" + '.' + dns_domain

        # find the interface that matches the dns_domain
        # use that interface's IP addresses for the glue record
        top_level_iface = None

        for iface in self._cfg["interfaces"]:
            vlan_domain = iface["vlan"]["domain"]
            # matches or is subdomain
            if dns_domain in vlan_domain:
                top_level_iface = iface
                break

        if not top_level_iface:
            raise ValueError(f"cannot find interface on DNS server with a vlan domain matching '{dns_domain}'")

        top_level = {
            "name": "top-level",
            "domain": dns_domain,
            "ipv4_address": top_level_iface["ipv4_address"],
            "ipv6_address": top_level_iface["ipv6_address"],
            "ipv4_subnet": top_level_iface["vlan"]["ipv4_subnet"],
            "ipv6_subnet": top_level_iface["vlan"]["ipv6_subnet"],
        }

        _add_zone(setup, top_level, dns_domain, dns_server)

        setup.comment("create glue record")
        # should always output since ip4_address was validated to not be dhcp
        # glue record does not need PTR entries
        _add_entry(setup, top_level, add_ptr=False)
        setup.blank()

        # forward to local dns on port 553
        # will add other vlan zones below
        forward_zones = [self._cfg["dns_domain"]]

        # specific addresses to bind to; add each interface
        listen_addresses = ["127.0.0.1", "::1"]
        # subnets that can make dns queries; add each vlan's subnet
        allow_subnets = ["127.0.0.1", "::1"]

        # note walking interfaces, then vlans in the interface's vswitch
        # if an interface is not defined for a vswitch, its vlans
        #  _will not_ be able to resolve DNS queries unless the router routes DNS queries correctly
        for top_level_iface in self._cfg["interfaces"]:
            if top_level_iface["type"] not in {"std", "vlan"}:
                continue

            listen_addresses.append(str(top_level_iface["ipv4_address"]))
            if top_level_iface["ipv6_address"] is not None:
                listen_addresses.append(str(top_level_iface["ipv6_address"]))

            for vlan in top_level_iface["vswitch"]["vlans"]:
                # no domain => no dns
                if not vlan["domain"]:
                    continue

                _add_zone(setup, vlan, dns_domain, dns_server)

                forward_zones.append(vlan["domain"])
                forward_zones.append(address.rptr_ipv4(vlan["ipv4_subnet"]))

                allow_subnets.append(str(vlan["ipv4_subnet"]))

                if vlan["ipv6_subnet"]:
                    forward_zones.append(address.rptr_ipv6(vlan["ipv6_subnet"]))
                    allow_subnets.append(str(vlan["ipv6_subnet"]))

        _create_host_entries(setup, self._cfg, dns_domain)
        # no entries needed for DHCP reservations; DDNS will dynamically add the host when it requests an address
        _create_static_host_entries(setup, self._cfg)

        setup.append("pdnsutil rectify-all-zones")

        web_allow_from = ["127.0.0.1", "::1"]

        # allow the metrics server to contact PDNS's webserver for metrics
        if ("metrics" in self._cfg["roles_to_hostnames"]) \
                and ("pdns" in self._cfg["metrics"]) and self._cfg["metrics"]["pdns"]["enabled"]:
            for hostname in self._cfg["roles_to_hostnames"]["metrics"]:
                host_cfg = self._cfg["hosts"][hostname]

                for match in interfaces.find_ips_to_interfaces(self._cfg, host_cfg["interfaces"], first_match_only=False):
                    if match["ipv4_address"]:
                        web_allow_from.append(str(match["ipv4_address"]))
                    if match["ipv6_address"]:
                        web_allow_from.append(str(match["ipv6_address"]))

        pdns_conf = {
            "dns_server": dns_server,
            "listen_addresses": ", ".join(listen_addresses),
            "web_allow_from": ", ".join(web_allow_from)
        }

        file.substitute_and_write(self.name, "pdns.conf", pdns_conf, output_dir)

        recursor = file.load_yaml_string(file.read_template(self.name, "recursor.yml"))

        recursor["incoming"]["listen"] = listen_addresses
        recursor["incoming"]["allow_from"] = allow_subnets
        recursor["recursor"]["export_etc_hosts_search_suffix"] = dns_domain
        # do not forward known zones; query internal DNS
        recursor["recursor"]["forward_zones"] = [{
            "zone": zone,
            "forwarders": ["127.0.0.1:553"]
        } for zone in forward_zones]
        # forward everything else to external DNS
        recursor["recursor"]["forward_zones_recurse"] = [{
            "zone": ".",
            "forwarders": [str(ip) for ip in self._cfg["external_dns"]]
        }]
        recursor["webservice"]["allow_from"] = web_allow_from

        file.write("recursor.yml", file.output_yaml(recursor), output_dir)

        # directly add external hostnames to /etc/hosts; PDSN recursor will serve these
        if self._cfg["external_hosts"]:
            hosts = [""]
            output = False

            for external in self._cfg["external_hosts"]:
                output = True
                hostnames = " ".join(external["hostnames"])
                hosts.append(str(external["ipv4_address"]) + " " + hostnames)

                if external["ipv6_address"]:
                    hosts.append(str(external["ipv6_address"]) + " " + hostnames)

            if output:
                hosts.append("")
                file.write("external_hosts", "\n".join(hosts), output_dir)
                setup.blank()
                setup.comment("assemble complete hosts file")
                setup.append("cat $DIR/external_hosts >> /etc/hosts")


def _add_zone(setup: shell.ShellScript, vlan: dict, dns_domain: str, dns_server: str):
    top_level = False

    if vlan["name"] == "top-level":
        setup.comment("creating zone for top-level domain")
        top_level = True
    else:
        setup.comment(f"create zone for '{vlan['name']}' vlan")

        # delegation record
        domain = vlan["domain"][:vlan["domain"].index(".") + 1]  # + 1 to include the .
        setup.append(f"pdnsutil add-record {dns_domain} {domain} NS {dns_server}")

    # forward zone
    setup.append(f"pdnsutil create-zone {vlan['domain']} {dns_server}")
    setup.append(f"pdnsutil secure-zone {vlan['domain']}")

    if top_level:
        # no reverse zones; only allow updates to the top-level domain from localhost, the default
        setup.blank()
        return

    subnets = []

    # reverse zones
    if vlan["ipv4_subnet"]:
        domain = address.rptr_ipv4(vlan["ipv4_subnet"])
        setup.append(f"pdnsutil create-zone {domain} {dns_server}")
        setup.append(f"pdnsutil secure-zone {domain}")

        subnets.append(str(vlan["ipv4_subnet"]))

    if vlan["ipv6_subnet"]:
        domain = address.rptr_ipv6(vlan["ipv6_subnet"])
        setup.append(f"pdnsutil create-zone {domain} {dns_server}")
        setup.append(f"pdnsutil secure-zone {domain}")

        subnets.append(str(vlan["ipv6_subnet"]))

    setup.append(f"pdnsutil set-meta {vlan['domain']} ALLOW-DNSUPDATE-FROM {' '.join(subnets)}")

    setup.blank()


def _add_entry(setup: shell.ShellScript, host: dict, add_ptr: bool = True) -> bool:
    # create A, AAAA and PTR records for each host
    domain = host["domain"]

    if host["name"] == "top-level":
        # ignore actual host name and create a glue record for the dns server
        name = "dns"
    else:
        name = host["name"]

    output = False

    if host["ipv4_address"] != "dhcp":
        setup.append(f"pdnsutil add-record {domain} {name} A {str(host['ipv4_address'])}")

        if add_ptr:
            rdomain = address.rptr_ipv4(host["ipv4_subnet"])
            ptr = address.hostpart_ipv4(host["ipv4_address"])
            setup.append(f"pdnsutil add-record {rdomain} {ptr} PTR {name}.{domain}")

        output = True

    if host["ipv6_address"]:
        setup.append(f"pdnsutil add-record {domain} {name} AAAA {str(host['ipv6_address'])}")

        if add_ptr:
            rdomain = address.rptr_ipv6(host["ipv6_subnet"])
            ptr = address.hostpart_ipv6(host["ipv6_address"], host["ipv6_subnet"].prefixlen)
            setup.append(f"pdnsutil add-record {rdomain} {ptr} PTR {name}.{domain}")

        output = True

    return output


def _add_cname(setup: shell.ShellScript,  alias: str, host: dict):
    # create CNAMEs for aliases
    domain = host['domain']
    setup.append(f"pdnsutil add-record {domain} {alias} CNAME {host['name']}.{domain}")


def _create_host_entries(setup: shell.ShellScript, cfg: dict, dns_domain: str):
    setup.comment("DNS entries for each host")

    for host_cfg in cfg["hosts"].values():
        # add a top-level CNAME for each alias if a top-level domain is defined
        # otherwise, just add aliases in each host's interface domains (see below)
        if cfg["domain"]:
            output = False
            domain = cfg["domain"]
            host_domain = host_cfg['primary_domain'] if host_cfg['primary_domain'] else domain

            for alias in host_cfg["aliases"]:
                # 'dns' entry already covered by glue record
                if alias != "dns":
                    hostname = host_cfg['hostname'] + '.' + host_domain
                    setup.append(f"pdnsutil add-record {domain} {alias} CNAME {hostname}")
                    output = True

            if output:
                setup.blank()

        for iface in host_cfg["interfaces"]:
            # skip port, vlan since they will never have subnets
            # skip uplink interfaces since this is internal only DNS
            if iface["type"] not in {"std", "vlan"}:
                continue

            vlan = iface["vlan"]

            # no domain name => no DNS
            if not vlan["domain"]:
                continue

            if (iface["ipv4_address"] == "dhcp") and not iface["ipv6_address"]:
                continue

            host = {
                "name": host_cfg["hostname"],
                "domain": vlan["domain"],
                "ipv4_address": iface["ipv4_address"],
                "ipv6_address": iface["ipv6_address"],
                "ipv4_subnet": iface["vlan"]["ipv4_subnet"],
                "ipv6_subnet": iface["vlan"]["ipv6_subnet"],
            }

            # DNS entries for each vlan / domain the host has access to
            output = _add_entry(setup, host)

            # aliases already added at top-level
            if vlan["domain"] == cfg["domain"]:
                continue

            # add CNAMES for each alias
            for alias in host_cfg["aliases"]:
                if (alias == "dns") and (vlan["domain"] == dns_domain):
                    # 'dns' entry already covered by glue record
                    continue
                _add_cname(setup, alias, host)
                output |= True

            # blank after each interface
            if output:
                setup.blank()


def _create_static_host_entries(setup: shell.ShellScript, cfg: dict):
    setup.comment("DNS entries for each static_host")

    for vswitch in cfg["vswitches"].values():
        for vlan in vswitch["vlans"]:
            # no domain name => no DNS
            if not vlan["domain"]:
                continue

            for host in vlan["static_hosts"]:
                entry = {
                    "name": host["hostname"],
                    "domain": vlan["domain"],
                    "ipv4_address": host["ipv4_address"] if host["ipv4_address"] else "dhcp",
                    "ipv6_address": host["ipv6_address"],
                    "ipv4_subnet": vlan["ipv4_subnet"],
                    "ipv6_subnet": vlan["ipv6_subnet"],
                }

                output = _add_entry(setup, entry)

                for alias in host["aliases"]:
                    _add_cname(setup, alias, host)
                    output |= True

                # blank after each host
                if output:
                    setup.blank()
