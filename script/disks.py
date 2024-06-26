"""Create shell script fragments for formatting disks and adding /etc/fstab entries in setup scripts."""
import os.path

import script.shell as shell


def from_config(cfg: dict, setup: shell.ShellScript):
    # create disks, format them and add fstab entries, as needed
    # defer to other roles if mounting is needed during setup
    for disk in cfg["disks"]:
        if disk["name"] == "system":
            continue  # base host setup will handle formatting the OS disk

        if (disk["type"] == "passthrough"):
            # for host passthrough, let other roles format the disk and set the mountpoint, if needed
            continue

        if cfg["is_vm"]:
            # for vms, setup the disk before chroot
            if disk["type"] == "img":
                # create the image in the outermost script
                # other config will need to move the image to correct location _inside_ the VM host
                # split for better formatting in output
                cfg["unnested_before_chroot"].extend(_create_image(disk).split("\n"))
            elif disk["type"] == "device":
                # note formatting with the host's disk path; it will be a different dev (e.g. vda) in a running vm
                cfg["before_chroot"].append(format(disk, "host_path"))

            cfg["before_chroot"].append(_add_uuid_to_envvars(disk))
        else:
            # for physical servers, configure the disk during setup
            if disk["type"] == "img":
                # TODO config.disks does not actually allow this
                # would need to set the 'loop' option in create_fstab_entry()
                setup.append(_create_image(disk))
            elif disk["type"] == "device":
                setup.append(format(disk, "path"))

            setup.append(_set_uuid_to_local_var(disk))
            setup.blank()


def _create_image(disk: dict) -> str:
    """Output the commands to create and format a disk image."""
    path = disk["host_path"]
    dir = os.path.dirname(path)
    format = f"\n  mkfs.{disk['fs_type']} \"{path}\"" if disk["format"] else ""

    # assume VM and UUID is written to $SETUP_TMP/envvars
    return f"""if [ ! -f "{path}" ]; then
  log "Creating & formatting '{disk['name']}' disk image"
  mkdir -p {dir}
  truncate -s {disk['size_mb']}M {path}
  sync{format}
else
  log "Reusing existing '{disk['name']}' disk image"
fi
"""


def format(disk: dict, path_key: str) -> str:
    path = disk[path_key]
    # for loop checks partitions if disk path is a full disk
    return f"""# only format the '{disk['name']}' disk if there are no existing, formatted partitions
has_fs=false
for fs in $(lsblk -ln -o FSTYPE {path}); do
  if [ -n $fs ]; then
    has_fs=true
    break
  fi
done
if [ "$has_fs" == "false" ]; then
  log "Formatting {path} as {disk['fs_type']} for '{disk['name']}'"
  mkfs.{disk['fs_type']} {path}
else
  log "Not reformatting {path} for '{disk['name']}'"
fi
"""


def _add_uuid_to_envvars(disk: dict) -> str:
    # for vms, write the UUID to envvars so it can be passed from yodel.sh to setup.sh
    # use blkid because lsblk does not work on disk images
    return f"echo \"{disk['name'].upper()}_UUID=$(blkid {disk['host_path']} | cut -d\\\" -f2)\" >> $SETUP_TMP/envvars\n"


def _set_uuid_to_local_var(disk: dict) -> str:
    # note, once partitioned, lsblk returns UUIDs for all partitions, not the top-level partition like blkid
    # this many be an issue on reinstalls
    return f"{disk['name'].upper()}_UUID=$(lsblk -ln -o UUID {disk['path']})"


def create_fstab_entry(disk: dict) -> str:
    """Add an entry to /etc/fstab for the given disk UUID & mount point."""
    if not disk.get("mountpoint"):
        # base config or other roles should have set the mountpoint
        raise ValueError(f"no mountpoint defined for disk '{disk['name']}'")

    return f"# mount '{disk['name']}' disk at boot\n" + \
        f"echo -e \"UUID=${disk['name'].upper()}_UUID\\t{disk['mountpoint']}\\t{disk['fs_type']}\\trw,relatime\\t0\\t2\"" + \
        " >> /etc/fstab"


def get_real_path(disk: dict) -> str:
    """Return the real path of the disk. 
    Using by-id will cause the path to end up in fstab which will be unable to boot."""
    if "/dev/disk/by-id" in disk["path"]:
        return f"$(cd /dev/disk/by-id/; realpath {disk['path']})"
    else:
        return disk["path"]
