"""Helper script to update a virsh vm definition, removing the data added by add_boot_iso.py.

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
        boot.attrib["dev"] = "hd"
    else:
        xml.SubElement(os, "boot", {"dev": "hd"})

    menu = os.find("bootmenu")

    if menu is not None:
        os.remove(menu)

# remove the cdrom, hdc
devices = domain.find("devices")

if devices is None:
    raise KeyError(f"no <devices> in {domain_xml}")

disks = devices.findall("disk")

for i, disk in enumerate(disks, start=1):
    target = disk.find("target")

    if target is None:
        raise KeyError(f"no <target> for disk {i}")
    if not "dev" in target.attrib:
        raise KeyError(f"no 'dev' attribute for <target> disk {i}")

    dev = target.attrib["dev"]

    if dev == "hdc":
        devices.remove(disk)

xml.indent(domain, space="  ")
xml.dump(domain)
