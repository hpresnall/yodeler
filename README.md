# Yodeler
**automated, self-contained, simple Alpine VM setup**

_this is a work in progress_

Yodeler is an opinionated, limited scope, orchestration framework. Yodeler's primary use case is standing up a new KVM
host and all the associated VMs needed to run a small, moderate traffic network. The design is primarily based on home
lab usage, but could be used for any configuration or network topology. It can automatically create and configure a
set of KVM virtual machines running [Alpine Linux](https://alpinelinux.org/).

Yodeler attempts to be as self-contained as possible. Configuration can be done on any system that can run Python 3.
Running Yodler turns the YAML configuration files into a set of _static shell scripts_. These scripts can then be run
from the Alpine install media on a new physical KVM host. The scripts will install Alpine, configure the host and
setup & configure all the required VMs.

Yodeler is a standalone program. _No extra software is required to run on each VM._ VMs are meant to be immutable.
Configuration changes imply destroying the old VM and creating a new one. This is a manual process and there are no
processes running on the KVM host that will trigger a VM rebuild.

Yodeler will (_eventually_) know how to do the following:

1. Setup an [Alpine](https://www.alpinelinux.org) based KVM host
1. Create minimal, basic Alpine VMs with small footprints and memory requirements
1. Configure basic [Awall](https://wiki.alpinelinux.org/wiki/How-To_Alpine_Wall) firewalls 
1. Manage [Open vSwitch](https://www.openvswitch.org) vswitches with VLAN support
1. Configure routers using Shorewall & iptables (eventually nftables)
1. Configure DNS / DHCP servers based on [PowerDNS](https://www.powerdns.com) and [Kea](https://www.isc.org/kea/)
1. Make IPv6 prefix delegation requests via [dhcpcd](https://github.com/NetworkConfiguration/dhcpcd) and distribute to subnets via radvd
1. Configure metrics & monitoring using Grafana and Prometheus

See [the roadmap](ROADMAP.md) for plans & progress.