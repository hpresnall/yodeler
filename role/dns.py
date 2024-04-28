"""Configuration & setup for a PowerDNS server."""
from role.roles import Role

import util.file as file
import util.address as address

import script.shell as shell
import script.sysctl as sysctl

import config.interfaces as interfaces


class Dns(Role):
    """DNS defines the configuration needed to setup PowerDNS. Configures both the DNS server and a recursor to
    handle internal and external DNS."""

    def additional_packages(self):
        return {"pdns", "pdns-recursor", "pdns-backend-sqlite3", "pdns-doc", "pdns-openrc", "bind-tools"}

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

        accessible_vlans = interfaces.check_accessiblity(self._cfg["interfaces"],
                                                         self._cfg["vswitches"].values())

        if accessible_vlans:
            raise ValueError(f"host '{self._cfg['hostname']}' does not have access to vlans {accessible_vlans}")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        # fake isp runs its own dns
        return 0 if 'fakeisp' in site_cfg["roles_to_hostnames"] else 1

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return 2  # no need for additional redundancy

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        """Create the scripts and configuration files for the given host's configuration."""
        sysctl.enable_tcp_fastopen(setup, output_dir)

        # scripts for creating the blackhole file
        file.copy_template("dns", "build_recursor_lua.sh", output_dir)
        file.copy_template("dns", "create_lua_blackhole.py", output_dir)

        if self._cfg["is_vm"]:
            # build in vm's build image
            self._cfg["before_chroot"].append(file.substitute("dns", "before_chroot.sh", self._cfg))
            setup.comment("blackhole script created before chroot in vmhost's build image")
        else:
            # build locally
            setup.comment("build blackhole script")
            setup.append("chmod +x $DIR/build_recursor_lua.sh")
            setup.append("mkdir build")
            setup.append("$DIR/build_recursor_lua.sh")
        setup.blank()

        setup.append(f"install -o pdns -g pdns -m 600 $DIR/pdns.conf /etc/pdns")
        setup.append(f"install -o recursor -g recursor -m 600 $DIR/recursor.conf /etc/pdns")
        setup.append(f"install -o recursor -g recursor -m 600 /tmp/blackhole.lua /etc/pdns")
        setup.blank()

        setup.comment("ensure startup does not log to the console")
        setup.append("sed -i -e \"s#\\${daemon}#\\${daemon} 2>&1 > /dev/null#g\" /etc/init.d/pdns-recursor")
        setup.blank()

        setup.service("pdns")
        setup.service("pdns-recursor")
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
        forward_zones = [self._cfg["dns_domain"] + "=127.0.0.1:553"]

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
                if vlan["domain"]:
                    _add_zone(setup, vlan, dns_domain, dns_server)

                    forward_zones.append(vlan["domain"] + "=127.0.0.1:553")

                    allow_subnets.append(str(vlan["ipv4_subnet"]))

                    if vlan["ipv6_subnet"]:
                        allow_subnets.append(str(vlan["ipv6_subnet"]))

        _create_host_entries(setup, self._cfg, dns_domain)
        _create_reservation_entries(setup, self._cfg)

        setup.append("pdnsutil rectify-all-zones")

        web_allow_from = ["127.0.0.1", "::1"]

        # allow the metrics server to contact PDNS's webserver for metrics
        if self._cfg["metrics"] and self._cfg["metrics"]["pdns"]["enabled"]:
            for hostname in self._cfg["roles_to_hostnames"]["metrics"]:
                host_cfg = self._cfg["hosts"][hostname]

                for match in interfaces.find_ips_to_interfaces(host_cfg, self._cfg["interfaces"], first_match_only=False):
                    if match["ipv4_address"]:
                        web_allow_from.append(str(match["ipv4_address"]))
                    if match["ipv6_address"]:
                        web_allow_from.append(str(match["ipv6_address"]))

        pdns_conf = {
            "dns_server": dns_server,
            "dns_domain": dns_domain,
            "forward_zones": ", ".join(forward_zones),
            "external_dns": ";".join(self._cfg["external_dns"]),  # note ; not comma and no spaces
            "listen_addresses": ", ".join(listen_addresses),
            "allow_subnets": ", ".join(allow_subnets),
            "web_allow_from": ", ".join(web_allow_from)
        }

        file.write("pdns.conf", file.substitute(self.name, "pdns.conf", pdns_conf), output_dir)
        file.write("recursor.conf", file.substitute(self.name, "recursor.conf", pdns_conf), output_dir)

        if self._cfg["additional_dns_entries"]:
            hosts = [""]
            for additional_dns in self._cfg["additional_dns_entries"]:
                hosts.append(str(additional_dns["ipv4_address"]) + " " + " ".join(additional_dns["hostnames"]))

                if "ipv6_address" in additional_dns:
                    hosts.append(str(additional_dns["ipv6_address"]) + " " + " ".join(additional_dns["hostnames"]))

            hosts.append("")
            file.write("other_hosts", "\n".join(hosts), output_dir)
            setup.blank()
            setup.comment("assemble complete hosts file")
            setup.append("cat $DIR/other_hosts >> /etc/hosts")
            setup.append("cat /tmp/hosts >> /etc/hosts")


def _add_zone(setup: shell.ShellScript, vlan: dict, dns_domain: str, dns_server: str):
    if vlan["name"] == "top-level":
        setup.comment("creating zone for top-level domain")
        vlan["name"] = "dns"
    else:
        setup.comment(f"create zone for '{vlan['name']}' vlan")

        # delegation record
        domain = vlan["domain"][:vlan["domain"].index(".") + 1]  # + 1 to include the .
        setup.append(f"pdnsutil add-record {dns_domain} {domain} NS {dns_server}")

    # forward zone
    setup.append(f"pdnsutil create-zone {vlan['domain']} {dns_server}")
    setup.append(f"pdnsutil secure-zone {vlan['domain']}")

    if vlan["name"] == "dns":
        # no reverse zones; only allow updates to the top-level domain from localhost, the default
        setup.blank()
        return

    subnets = []

    # reverse zones
    if vlan["ipv4_subnet"]:
        domain = str(address.rptr_ipv4(vlan["ipv4_subnet"]))
        setup.append(f"pdnsutil create-zone {domain} {dns_server}")
        setup.append(f"pdnsutil secure-zone {domain}")

        subnets.append(str(vlan["ipv4_subnet"]))

    if vlan["ipv6_subnet"]:
        domain = str(address.rptr_ipv6(vlan["ipv6_subnet"]))
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


def _add_alias(setup: shell.ShellScript,  alias: str, host: dict):
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

            # CNAMES for each alias
            for alias in host_cfg["aliases"]:
                if (alias == "dns") and (vlan["domain"] == dns_domain):
                    # 'dns' entry already covered by glue record
                    continue
                _add_alias(setup, alias, host)
                output |= True

            # blank after each interface
            if output:
                setup.blank()


def _create_reservation_entries(setup: shell.ShellScript, cfg: dict):
    setup.comment("DNS entries for each DHCP reservation")

    for vswitch in cfg["vswitches"].values():
        for vlan in vswitch["vlans"]:
            # no domain name => no DNS
            if not vlan["domain"]:
                continue

            for res in vlan["dhcp_reservations"]:
                if res["ipv4_address"] or res["ipv6_address"]:
                    host = {
                        "name": res["hostname"],
                        "domain": vlan["domain"],
                        "ipv4_address": res["ipv4_address"] if res["ipv4_address"] else "dhcp",
                        "ipv6_address": res["ipv6_address"],
                        "ipv4_subnet": vlan["ipv4_subnet"],
                        "ipv6_subnet": vlan["ipv6_subnet"],
                    }

                    output = _add_entry(setup, host)

                    for alias in res["aliases"]:
                        _add_alias(setup, alias, host)
                        output |= True

                    if output:
                        setup.blank()
