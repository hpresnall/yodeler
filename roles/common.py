import os
import json
import xml.etree.ElementTree as xml

import util.shell
import util.file

# use Debian's better ifupdown and the Linux ip command, instead of Busybox's built-ins
packages = {"ifupdown", "iproute2"}


def setup(cfg, dir):
    common = util.shell.ShellScript("common.sh")

    common.append("echo \"Running common config\"")
    common.append("")

    common.append(_setup_repos(cfg))

    if not cfg["is_vm"]:
        # for physical servers, add packages manually
        # VMs will have packages installed as part of image creation
        common.append("# install necessary packages")
        common.append("apk -q update")
        common.append("apk -q add `cat $DIR/packages`")
        common.append("")

    cfg["remove_packages_str"] = " ".join(cfg["remove_packages"])
    common.append(util.file.substitute("templates/common/common.sh", cfg))

    if cfg["metrics"]:
        common.append(_setup_metrics)

    if cfg["local_firewall"]:
        common.append(_setup_local_firewall(cfg, dir))

    common.write_file(dir)

    _create_interfaces(cfg, dir)
    _create_resolv_conf(cfg, dir)
    _create_chrony_conf(cfg, dir)

    if cfg["is_vm"]:
        # create the XML vm definition
        _create_virsh_xml(cfg, dir)

        # note not adding create_vm to setup script
        # for VMs, create_vm.sh will run setup.sh _inside_ a chroot for the vm
        create_vm = util.shell.ShellScript("create_vm.sh")
        create_vm.append_self_dir()
        create_vm.append(util.file.substitute("templates/vm/create_vm.sh", cfg))
        create_vm.write_file(dir)
    else:
        # create Alpine setup answerfile for physical servers
        # use external DNS for initial Alpine setup
        cfg["external_dns_str"] = " ".join(cfg["external_dns"])
        util.file.write("answerfile", util.file.substitute("templates/alpine/answerfile", cfg), dir)

        install = util.shell.ShellScript("install_alpine.sh")
        install.append_self_dir()
        install.append(util.file.substitute("templates/alpine/install_alpine.sh", cfg))
        install.write_file(dir)
        # note not returning install script
        # it must be run manually by another process

    return [common.name]


def _setup_repos(cfg):
    repos = cfg["alpine_repositories"]
    b = []

    # overwrite on first, append on subsequent
    b.append("# setup APK repos")
    b.append(f"echo {repos[0]} > /etc/apk/repositories")

    repos = repos[1:]
    for r in repos:
        b.append(f"echo {r} >> /etc/apk/repositories")
    b.append("")

    return "\n".join(b)


def _create_interfaces(cfg, dir):
    b = []

    b.append("auto lo")
    b.append("iface lo inet loopback")
    b.append("iface lo inet6 loopback")
    b.append("")

    for iface in cfg["interfaces"]:
        if iface["ipv4_method"] == "static":
            if iface["vlan"]["routable"]:
                template = _ipv4_static_template
            else:
                template = _ipv4_static_unroutable_template
            b.append(template.format_map(iface))
        elif iface["ipv4_method"] == "dhcp":
            b.append("auto {name}\niface {name} inet {ipv4_method}".format_map(iface))
        else:
            raise KeyError(f"invalid ipv4_method {iface['ipv4_method']} for interface {iface}")

        if iface["ipv6_method"] == "manual":
            b.append("iface {name} inet6 {ipv6_method}".format_map(iface))
        else:
            b.append(_ipv6_auto_template.format_map(iface))

            if iface["ipv6_address"] is not None:
                b.append(_ipv6_address_template.format_map(iface))

        b.append("")

    util.file.write("interfaces", "\n".join(b), dir)


def _create_resolv_conf(cfg, dir):
    # determine if any interface is using DHCP
    dhcp = False
    search_domains = []
    for iface in cfg["interfaces"]:
        dhcp |= iface["ipv4_method"] == "dhcp"
        # search all vlan domains
        search_domains.append(iface["vlan"]["domain"])

    b = []

    if not dhcp:
        if (cfg["primary_domain"]):
            b.append(f"domain {cfg['primary_domain']}")

        if cfg["local_dns"]:
            # can search local domains if there is local dns
            search_domains.append(cfg["domain"])
            b.append("search {}".format(" ".join(search_domains)))

            nameservers = cfg["local_dns"]
        else:
            nameservers = cfg["external_dns"]

        for server in nameservers:
            b.append("nameserver " + server)
        b.append("")
    # else leave empty & assume DHCP will setup resolv.confg otherwise

    util.file.write("resolv.conf.head", "\n".join(b), dir)


def _setup_local_firewall(cfg, dir):
    # create all JSON config from template
    # see https://wiki.alpinelinux.org/wiki/Zero-To-Awall

    # base json template; add a zone and policy for each interface
    base = {"description": "base zones and policies", "zone": {}, "policy": []}

    # load all template services
    services = {}
    for path in os.listdir("templates/awall"):
        with open(os.path.join("templates/awall", path)) as f:
            service = json.load(f)
        # assume service has a single filter and it is for input
        service["filter"][0]["in"] = []
        services[path] = service

    for iface in cfg["interfaces"]:
        zone = iface["firewall_zone"]
        name = iface["name"]

        # add zones for each interface
        base["zone"][zone] = {"iface": name}
        # allow all traffic out
        # allow no traffic in, except as configured by servics
        base["policy"].append({"out": zone, "action": "accept"})
        base["policy"].append({"in": zone, "action": "drop"})

        # all zones can retrieve traffic for all services
        for service in services.values():
            service["filter"][0]["in"].append(zone)

    # write JSON config to awall subdirectory
    awall = os.path.join(dir, "awall")
    os.mkdir(awall)

    b = ["# configure awall"]
    b.append("rootinstall $DIR/awall/base.json /etc/awall/optional")
    b.append("awall enable base")

    util.file.write("base.json",  json.dumps(base, indent=2), awall)

    for name, service in services.items():
        util.file.write(name, json.dumps(service, indent=2), awall)

        b.append(f"rootinstall $DIR/awall/{name} /etc/awall/optional")
        b.append("awall enable {}".format(name[:-5]))  # name without .json

    b.append("")
    b.append("# create iptables rules and apply at boot")
    b.append("awall translate -o /tmp")
    b.append("rootinstall /tmp/rules-save /tmp/rules6-save /etc/iptables")
    b.append("rc-update add iptables boot")
    b.append("rc-update add ip6tables boot")

    return "\n".join(b)


def _create_chrony_conf(cfg, dir):
    b = []

    # use local NTP server if there is one defined
    if "local_ntp" in cfg:
        server = cfg["local_ntp"]
        b.append(f"server {server} iburst")
        b.append(f"initstepslew 10 {server}")
    else:
        servers = cfg["ntp_pool_servers"]
        for server in servers:
            b.append(f"server {server} iburst")
        b.append("initstepslew 10 {}".format(" ".join(servers)))

    b.append("driftfile /var/lib/chrony/chrony.drift")
    b.append("rtcsync")

    util.file.write("chrony.conf", "\n".join(b), dir)


def _create_virsh_xml(cfg, dir):
    template = xml.parse("templates/vm/server.xml")
    vm = template.getroot()

    name = vm.find("name")
    name.text = cfg["hostname"]

    memory = vm.find("memory")
    memory.text = str(cfg["memory_mb"])

    vcpu = vm.find("vcpu")
    vcpu.text = str(cfg["vcpus"])

    devices = vm.find("devices")

    disk_source = devices.find("disk/source")
    disk_source.attrib["file"] = f"{cfg['vm_images_path']}/{cfg['hostname']}.img"

    for iface in cfg["interfaces"]:
        vlan_name = iface["vlan"]["name"]
        interface = xml.SubElement(devices, "interface")
        interface.attrib["type"] = "network"
        xml.SubElement(interface, "source", {"network": iface["vswitch"]["name"], "portgroup": vlan_name})
        xml.SubElement(interface, "target", {"dev": f"{cfg['hostname']}-{vlan_name}"})
        xml.SubElement(interface, "model", {"type": "virtio"})

    template.write(os.path.join(dir, cfg["hostname"] + ".xml"))


_ipv4_static_template = """auto {name}
iface {name} inet {ipv4_method}
  address {ipv4_address}
  netmask {ipv4_netmask}
  gateway {ipv4_gateway}"""

_ipv4_static_unroutable_template = """auto {name}
iface {name} inet {ipv4_method}
  address {ipv4_address}
  netmask {ipv4_netmask}"""

_ipv6_auto_template = """iface {name} inet6 {ipv6_method}
  dhcp {ipv6_dhcp}
  accept_ra {accept_ra}
  privext {privext}"""

_ipv6_address_template = """  post-up ip -6 addr add {ipv6_address}/{ipv6_prefixlen} dev {name}
  pre-down ip -6 addr del {ipv6_address}/{ipv6_prefixlen} dev {name}"""

_setup_metrics = """# setup Prometheus
rc-update add node-exporter default

echo "ARGS=\\\"--log.level=warn\
--no-collector.cpufreq\
--no-collector.entropy\
--no-collector.hwmon\
--no-collector.ipvs\
--no-collector.nfs\
--no-collector.nfsd\
--no-collector.textfile\
--no-collector.timex\
--no-collector.xfs\
--no-collector.zfs\
--web.disable-exporter-metrics\
--collector.diskstats.ignored-devices='^(ram|loop|fd|(h|s|v|xv)d[a-z]|nbd|sr|nvme\\d+n\\d+p)\\d+$'\
--collector.filesystem.ignored-fs-types='^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tmpfs|tracefs)$'\\\""\
> /etc/conf.d/node-exporter
"""
