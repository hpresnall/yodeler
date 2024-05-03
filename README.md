# Yodeler
**automated, self-contained, minimal VM setup; aka yelling at Alpine Linux**

_this is a work in progress_

Yodeler is an opinionated, limited scope, orchestration framework. Yodeler's primary use case is standing up a new KVM
host and all the associated VMs needed to run a small, moderate traffic network. The design is primarily based on home
lab usage, but could be used for any configuration or network topology. It can automatically create and configure a
set of KVM virtual machines running [Alpine Linux](https://alpinelinux.org/).

Yodeler attempts to be as self-contained as possible. All that is needed is a single computer and an internet connection.
Yodeler turns YAML configuration files into a set of _static shell scripts_. These scripts can then be run from
bootable Alpine install media to setup a new host. The scripts will install Alpine, configure KVM & setup all the
desired VMs.

Yodeler is a standalone Python 3 program and is run before system setup. _No extra software is required to run configured
systems_. YAML configuration files can be created and Yodler can be on any system that has Python 3.

Systems are meant to be immutable. Configuration changes imply destroying the old VM and creating a new one. This is a
manual process; there are no processes running on the KVM host that will trigger a VM rebuild.

Yodeler knows how to do the following:

1. Setup an [Alpine](https://www.alpinelinux.org) based KVM host
1. Create minimal, basic Alpine VMs with small footprints and memory requirements
1. Configure basic [Awall](https://wiki.alpinelinux.org/wiki/How-To_Alpine_Wall) firewalls 
1. Manage [Open vSwitch](https://www.openvswitch.org) vswitches with VLAN support
1. Configure routers using Shorewall & iptables (eventually nftables)
1. Configure DNS / DHCP servers based on [PowerDNS](https://www.powerdns.com) and [Kea](https://www.isc.org/kea/) for both IPv4 and IPv6
1. Make IPv6 prefix delegation requests via [dhcpcd](https://github.com/NetworkConfiguration/dhcpcd) and distribute to subnets via radvd
1. Configure ZFS based Samba servers
1. Configure metrics & monitoring using Grafana and Prometheus (in progress)

See [the roadmap](ROADMAP.md) for plans & progress.