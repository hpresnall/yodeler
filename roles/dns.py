"""Configuration & setup for a BIND9 DNS server."""
import os.path

import util.shell
import util.file
import util.address
import util.sysctl

import config.interfaces as interfaces

from roles.role import Role


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
        return 0 if 'fakeisp' in site_cfg["roles_to_hostnames"] else 1

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return 2  # no need for additional redundancy

    def write_config(self, setup: util.shell.ShellScript, output_dir: str):
        """Create the scripts and configuration files for the given host's configuration."""
        util.sysctl.enable_tcp_fastopen(setup, output_dir)

        setup.append(f"install -o pdns -g pdns -m 600 $DIR/pdns.conf /etc/pdns")
        setup.append(f"install -o recursor -g recursor -m 600 $DIR/recursor.conf /etc/pdns")
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

        pdns_conf = {
            "dns_server": dns_server,
            "dns_domain": dns_domain,
            "forward_zones": ",".join(forward_zones),
            "external_dns": ";".join(self._cfg["external_dns"]),
            "listen_addresses": ",".join(listen_addresses),
            "allow_subnets": ",".join(allow_subnets),
            "web_listen_addresses": "0.0.0.0",
            "web_allow_subnets": "127.0.0.1,::1"
        }

        util.file.write("pdns.conf", util.file.substitute("templates/dns/pdns.conf", pdns_conf), output_dir)
        util.file.write("recursor.conf", util.file.substitute("templates/dns/recursor.conf", pdns_conf), output_dir)


def _add_zone(setup: util.shell.ShellScript, vlan: dict, dns_domain: str, dns_server: str):
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
        domain = str(util.address.rptr_ipv4(vlan["ipv4_subnet"]))
        setup.append(f"pdnsutil create-zone {domain} {dns_server}")
        setup.append(f"pdnsutil secure-zone {domain}")

        subnets.append(str(vlan["ipv4_subnet"]))

    if vlan["ipv6_subnet"]:
        domain = str(util.address.rptr_ipv6(vlan["ipv6_subnet"]))
        setup.append(f"pdnsutil create-zone {domain} {dns_server}")
        setup.append(f"pdnsutil secure-zone {domain}")

        subnets.append(str(vlan["ipv6_subnet"]))

    setup.append(f"pdnsutil set-meta {vlan['domain']} ALLOW-DNSUPDATE-FROM {" ".join(subnets)}")

    setup.blank()


def _add_entry(setup: util.shell.ShellScript, host: dict, add_ptr: bool = True) -> bool:
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
            rdomain = util.address.rptr_ipv4(host["ipv4_subnet"])
            ptr = util.address.hostpart_ipv4(host["ipv4_address"])
            setup.append(f"pdnsutil add-record {rdomain} {ptr} PTR {name}.{domain}")

        output = True

    if host["ipv6_address"]:
        setup.append(f"pdnsutil add-record {domain} {name} AAAA {str(host['ipv6_address'])}")

        if add_ptr:
            rdomain = util.address.rptr_ipv6(host["ipv6_subnet"])
            ptr = util.address.hostpart_ipv6(host["ipv6_address"], host["ipv6_subnet"].prefixlen)
            setup.append(f"pdnsutil add-record {rdomain} {ptr} PTR {name}.{domain}")

        output = True

    return output


def _add_alias(setup: util.shell.ShellScript,  alias: str, host: dict):
    # create CNAMEs for aliases
    domain = host['domain']
    setup.append(f"pdnsutil add-record {domain} {alias} CNAME {host['name']}.{domain}")


def _create_host_entries(setup: util.shell.ShellScript, cfg: dict, dns_domain: str):
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


def _create_reservation_entries(setup: util.shell.ShellScript, cfg: dict):
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
