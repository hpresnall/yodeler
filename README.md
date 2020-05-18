# Yodeler
## automated Alpine VM setup

_this is a work in progress_

Yodeler is an opinionated way to automatically create and configure a set of KVM virtual machines running [Alpine Linux] (https://alpinelinux.org/). It is designed primarily for home lab usage, but could be used for any configuration or network topology. Yodeler's primary use case is standing up a new KVM host and all the associated VMs needed to run a small, self-contained network.

Yodeler attempts to be as self contained as possible. Configuration can be done on any system that can run Python 3. Running Yodler turns the YAML configuration file into a set of shell scripts that can then be run from the Alpine install media on a new physical KVM host. Yodler scripts will install Alpine, configure the host and setup & configure all the required VMs.

Yoderler is a standalone program. VMs are meant to be immutable. Configuration changes imply destroying the old VM and creating a new one. _No extra software is required to run on each VM._

Yodeler will (_eventually_) know how to configure the following:

1. A minimal, basic Alpine VM
1. An Alpine based KVM host
1. Multiple Openvswitch vswitches with multiple VLANs
1. Minimal Awall based firewalls
1. Routers based on Shorewall / iptables
1. DNS / DHCP servers based on Bind 9 and Kea
1. Dynamic IPv6 prefix delegation with radvd (internal) and udhcpd (external)
1. Metrics servers based on Grafana and Prometheus
