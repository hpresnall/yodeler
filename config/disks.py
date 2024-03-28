"""Handles parsing and validating disk configuration from host YAML files."""

import util.parse as parse
import util.pci as pci


def validate(cfg: dict):
    """Validate all the disks defined on the host."""
    disks = cfg["disks"] = parse.read_dict_list_plurals({"disk", "disks"}, cfg, "disks")
    cfg.pop("disk", None)

    names = set()
    paths = set()

    system_disk = None
    system_disk_idx = -1

    for i, disk in enumerate(disks, start=1):
        location = f"cfg[{cfg['hostname']}].disks[{i}]"

        # if only one disk, assume it is the system disk
        # if no disks, it will be added below
        if (len(disks) == 1) and ("name" not in disk):
            disk["name"] = "system"

        name = parse.non_empty_string("name", disk, location)

        if name in names:
            raise ValueError(f"duplicate disk name '{name}' for {location}")
        names.add(name)

        # root disk for the OS
        if "system" == name:
            system_disk = disk
            system_disk_idx = i - 1

        # disks can define a 'mountpoint' but it may be overridden by other config, so do not require it here
        if ("mountpoint" in disk) and not isinstance(disk["mountpoint"], str):
            raise ValueError(f"{location}.mountpoint must be a string")

        # default to img for vms and device for physical
        type = parse.set_default_string("type", disk, "img" if cfg["is_vm"] else "device")

        if "img" == type:
            if not cfg["is_vm"]:
                # possible, but no use case now
                # would require creating the image and then loop mounting it, probably outside of /etc/fstab
                raise ValueError(f"{location}: cannot create 'img' disk for physical server")

            # require path to image file on vmhost; optional size
            # system disk image is just named with the hostname
            postfix = "" if name == "system" else "_" + name
            path = disk.setdefault("path", f"{cfg['vm_images_path']}/{cfg['hostname']}{postfix}.img")

            int(disk.setdefault("size_mb", "1024"))

            disk["partition"] = ""
            parse.set_default_string("fs_type", disk, "ext4")
        elif "device" == type:
            # require /dev/ path; optional partition
            path = parse.non_empty_string("path", disk, location)

            if not path.startswith("/dev/"):
                raise ValueError(f"{location}.path '{path}' does not start with /dev/")

            disk["partition"] = str(disk.setdefault("partition", ""))
            parse.set_default_string("fs_type", disk, "ext4")
        elif "passthrough" == type:
            if not cfg["is_vm"]:
                # possible, but no use case now
                # would require associating pci addresses / ids to /dev/disk path
                # not difficult, but easier to just force 'device' disks pointing directly to the /dev path
                raise ValueError(f"{location}: cannot create 'passthrough' disk for physical server")

            # require path & PCI address
            # path is used during setup to mount the disk inside of chroot
            path = parse.non_empty_string("path", disk, location)
            address = parse.non_empty_string("pci_address", disk, location)

            if not path.startswith("/dev/"):
                raise ValueError(f"{location}.path '{path}' does not start with /dev/")

            disk["bus"], disk["slot"], disk["function"] = pci.split(address, location)

            # do not set fs_type; assume role will configure as needed
            disk["partition"] = ""  # only support complete devices
        else:
            raise ValueError(f"unknown {location}.type '{type}'; it must be 'img', 'device' or 'passthrough'")

        disk["path"] = path
        path += disk["partition"]

        if path in paths:
            raise ValueError(f"duplicate disk path '{path}' for {location}")
        paths.add(path)

    # define the system disk, if needed
    if system_disk:
        if system_disk_idx != 0:
            del disks[system_disk_idx]

            # ensure it is the first disk
            disks.insert(0, system_disk)

        if not cfg["is_vm"] and (system_disk["type"] != "device"):
            raise ValueError(f"physical host '{cfg['hostname']}' system disk type must be 'device'")
    else:
        if cfg["is_vm"]:
            # this image file will be created and formatted in yodel.sh by alpine-make-vm-image
            disk = {"name": "system", "type": "img", "size_mb": cfg["disk_size_mb"],
                    "path": f"{cfg['vm_images_path']}/{cfg['hostname']}.img"}
        else:
            disk = {"name": "system", "type": "device",
                    "path": "/dev/sda", "partition": "3"}

        # make it the first disk
        disks.insert(0, disk)
