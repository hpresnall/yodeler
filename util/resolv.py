"""Utility for /etc/resolv.confg configuration."""
import util.file


def create_conf(interfaces, host_domain, site_domain, local_dns, external_dns, output_dir):
    """Create resolv.conf and save it to the given directory.

    All values are optional. If no values are specified, no file is created.
    local_dns and external_dns should be an iterable of IP addresses.
    """
   # determine if any interface is using DHCP
    dhcp = False
    search_domains = []

    if interfaces is not None:
        for iface in interfaces:
            dhcp |= iface["ipv4_method"] == "dhcp"
            # search all vlan domains
            domain = iface["vlan"].get("domain")
            if (domain is not None) and (domain != ""):
                search_domains.append(domain)

    buffer = []

    if not dhcp:  # manually set DNS servers
        if local_dns:
            if host_domain and host_domain != "":
                buffer.append(f"domain {host_domain}")

            # can search local domains if there is local dns
            if search_domains and search_domains != "":
                search_domains.append(site_domain)

            if len(search_domains) > 0:
                buffer.append("search {}".format(" ".join(search_domains)))

            nameservers = local_dns
        else:
            nameservers = external_dns

        for server in nameservers:
            buffer.append("nameserver " + server)
        buffer.append("")
    # else leave empty & assume DHCP will setup resolv.conf

    # do not write out empty file
    if len(buffer) > 0:
        util.file.write("resolv.conf", "\n".join(buffer), output_dir)
