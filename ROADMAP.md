# Planned Functionality

## Alpine Configuration
- [x] Common setup tasks
- [x] Minimal VM creation
- [x] Basic awall firewall config
- [x] Generic configuration & setup for physical servers
- [ ] All-in-one, single system pysical server configuration
- [ ] All-in-one, router/DHCP/DNS VM configuration

## KVM Virtual Machine Host
- [x] Minimal KVM Server Configuration
- [x] Open vSwitch configuration with multiple switches and vlans
- [x] Automated VM setup for an entire site
- [x] Confiture apk_cache and pass it to install media & VMs
- [ ] Let's Encrypt support for wildcard domains and distribution to VMs

## Router
- [x] Basic interface configuration for each vswitch & vlan
- [x] Basic Shorewall configuration with routing
- [ ] nftables firewall configuration
- [ ] SMCroute config for multicast routing
- [x] dhcrelay config for DHCP between vlans
- [x] dhcpcd config for IPv6 DHCP prefix requests to ISPs & distribution to vlans
- [ ] Dynamic DNS updates for external addresses
- [ ] [WireGuard](https://www.wireguard.com/) VPN support

## DNS
- [x] Basic BIND 9 configuration
- [x] YAML-based configuration for additional DNS entries
- [ ] Bind alternatives? PowerDNS?
- [ ] Add / update IPv6 SLAAC addresses

## DHCP
- [x] Kea configuration for IPv4 and IPv6 with host reservations
- [x] Update DNS on DHCP changes
- [x] DHCP client support via dhcpcd for both IPv4 and IPv6 (autoconf & managed)
- [ ] Track DHCP reservations and IPv6 SLAAC addresses over time

## NTP
- [ ] Configure chronyd server

## Metrics
- [x] Configure Prometheus client on all systems
- [ ] Configure Prometheus server
- [ ] Configure Grafana
- [ ] Create / generate dashboards for all servers in a site
- [ ] Add OneWire support for sensor metrics
- [ ] Add SNMP support for network metrics

## Storage
- [ ] Configure Samba
- [ ] Add separate storage volume, outside of the VM
- [ ] Configure XFS
- [ ] Add PCI passthrough support for storage volumes
- [ ] Add backup and / or shared mount support for durable VM configuration data

## Build Server
- [ ] Configure basic build tools
- [ ] Configure golang builds
- [ ] Create process for building executables and sharing with other VMs
- [ ] Create durable build partition for builds without network access

## XWindows
- [ ] Configure basic XFCE GUI
- [ ] Setup simple desktop with standard plugins