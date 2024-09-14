"""Helper script to update a virsh vm definition to boot from a CD.

Assumes the following commands have already been run:
virsh attach-disk <vm> <iso_file> hdc --config --type cdrom --targetbus sata

Requires <path_to_xml> as a command line argument.
"""
import xml.etree.ElementTree as xml
import os.path
import sys

if len(sys.argv) == 1:
    print("virsh domain xml required")
    exit(1)

domain_xml = sys.argv[1]
domain = xml.parse(domain_xml).getroot()

# remove boot element from top-level os
os = domain.find("os")
if os is not None:
    boot = os.find("boot")

    if boot is not None:
        os.remove(boot)

    menu = os.find("bootmenu")

    if menu is None:
        xml.SubElement(os, "bootmenu", {"enable": "yes"})
    else:
        menu.attrib["enable"] = "yes"

# add boot order to the cdrom, hdc
devices = domain.find("devices")

if devices is None:
    raise KeyError(f"no <devices> in {domain_xml}")

updated = False
disks = devices.findall("disk")

for i, disk in enumerate(disks, start=1):
    target = disk.find("target")

    if target is None:
        raise KeyError(f"no <target> for disk {i}")
    if not "dev" in target.attrib:
        raise KeyError(f"no 'dev' attribute for <target> disk {i}")

    dev = target.attrib["dev"]

    if dev == "hdc":
        boot = disk.find("boot")

        if boot is None:
            xml.SubElement(disk, "boot", {"order": "1"})
        else:
            boot.attrib["order"] = "1"

        updated = True
        break

if not updated:
    print("did not find cdrom 'hdc' to update")
    exit(1)

xml.indent(domain, space="  ")
xml.dump(domain)
