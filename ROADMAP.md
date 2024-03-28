# Planned Functionality

## Alpine Configuration
- [x] Common setup tasks
- [x] Minimal VM creation
- [x] Basic awall firewall config
- [x] Generic configuration & setup for physical servers
- [x] All-in-one, router/DHCP/DNS pysical server configuration
- [ ] All-in-one, router/DHCP/DNS VM configuration

## KVM Virtual Machine Host
- [x] Minimal KVM Server Configuration
- [x] Open vSwitch configuration with multiple switches and vlans
- [x] Automated VM setup for an entire site
- [x] Configure apk_cache and pass it to install media & VMs
- [x] Support PCI passthrough of both disks & SR-IOV network interfaces
- [ ] Let's Encrypt support for wildcard domains and distribution to VMs

## Router
- [x] Basic interface configuration for each vswitch & vlan
- [x] Basic Shorewall configuration with routing
- [x] Ability to add custom firewall rules based on vlans, hosts, ipsets and ip addresses
- [ ] nftables firewall configuration
- [ ] SMCroute config for multicast routing
- [x] dhcrelay config for DHCP between vlans
- [x] dhcpcd config for IPv6 DHCP prefix requests to ISPs & distribution to vlans
- [ ] Dynamic DNS updates for external addresses
- [ ] [WireGuard](https://www.wireguard.com/) VPN support

## DNS
- [x] PowerDNS configuration
- [x] YAML-based configuration for additional DNS entries
- [x] Add DHCP reservations & aliases to DNS
- [x] Configure blackhole hosts file like Pi-Hole
- [ ] Add / update IPv6 SLAAC addresses
- [ ] DNSSEC

## DHCP
- [x] Kea configuration for IPv4 and IPv6 with host reservations
- [x] DDNS support to update DNS on DHCP changes
- [x] DHCP client support via dhcpcd for both IPv4 and IPv6 (autoconf & managed)
- [ ] Track DHCP reservations and IPv6 SLAAC addresses over time

## NTP
- [x] Configure chronyd server

## Metrics
- [x] Configure Prometheus client on all systems
- [ ] Configure Prometheus server
- [ ] Configure Grafana
- [ ] Create / generate dashboards for all servers in a site
- [ ] Add OneWire support for sensor metrics
- [ ] Add SNMP support for network metrics

## Storage
- [x] Configure Samba
- [x] Allow separate storage volume that can persist on VM rebuilds
- [x] Configure ZFS
- [x] Support for image, device and PCI passthrough disks on VMs
- [x] Add backup and / or shared mount support for durable VM configuration data
- [] Add backup scripts for each server role & configure nightly backups

## Build Server
- [x] Configure basic build tools
- [x] Create process for building executables and sharing with other VMs
- [x] Create durable build partition for builds without network access
- [] Allow custom scripts to run as part of server builds

## XWindows
- [x] Configure basic XFCE GUI
- [ ] Setup simple desktop with standard plugins

## Fake ISP
- [x] Basic configuration of an intermediate router / firewall for testing
- [x] Support for running a VM that can host _another_ Yodler site for testing
- [x] Full IPv4 & IPv6 address support, including prefix delegation to mimic an upstream ISP