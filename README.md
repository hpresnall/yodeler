# Yodeler
**automated, self-contained, simple Alpine VM setup**

_this is a work in progress_

Yodeler is an opinionated, limited scope, orchestration framework. Yodeler's primary use case is standing up a new KVM host and all the associated VMs needed to run a small, self-contained network. The design is primarily based on home lab usage, but could be used for any configuration or network topology.  It can automatically create and configure a set of KVM virtual machines running [Alpine Linux](https://alpinelinux.org/).

Yodeler attempts to be as self-contained as possible. Configuration can be done on any system that can run Python 3. Running Yodler turns the YAML configuration files into a set of static shell scripts. These scripts can then be run from the Alpine install media on a new physical KVM host. These scripts will install Alpine, configure the host and setup & configure all the required VMs.

Yodeler is a standalone program. _No extra software is required to run on each VM._ VMs are meant to be immutable. Configuration changes imply destroying the old VM and creating a new one.

Yodeler will (_eventually_) know how to configure the following:

1. A minimal, basic Alpine VM
1. An Alpine based KVM host
1. Multiple Openvswitch vswitches with multiple VLANs
1. Minimal Awall based firewalls
1. Routers based on Shorewall / iptables
1. DNS / DHCP servers based on Bind 9 and Kea
1. Dynamic IPv6 prefix delegation with radvd (internal) and udhcpd (external)
1. Metrics servers based on Grafana and Prometheus
