"""Utility functions for handling disks."""


def create_disk_image(hostname: str, disk_path: str, size: int, uuid_envvar_name: str) -> str:
    """Output the commands to create and format a disk image.

    The envvar holding the UUID of the disk must be unique within each host."""
    # assume VM and UUID is written to /tmp/envvars
    return f"""if [ ! -f "{disk_path}" ]; then
  truncate -s {size}M {disk_path}
  sync
  mkfs.ext4 {disk_path}
# else reuse existing disk image
fi
""" + _output_blkid(hostname, disk_path, uuid_envvar_name)


def format_disk(hostname: str, disk_path: str, uuid_envvar_name: str) -> str:
    return f"""# only format the build disk if there is no existing partition
blkid --match-token TYPE=ext4 {disk_path} || mkfs.ext4 {disk_path}
""" + _output_blkid(hostname, disk_path, uuid_envvar_name)


def _output_blkid(hostname: str, disk_path: str,  uuid_envvar_name: str) -> str:
    return f"echo \"{uuid_envvar_name}=$(blkid {disk_path} | cut -d\\\" -f2)\" >> /tmp/{hostname}/tmp/envvars"


def create_fstab_entry(uuid_envvar_name: str, mount_point: str) -> str:
    """Add an entry to /etc/fstab for the given disk UUID & mount point."""
    return f"echo -e \"UUID=${uuid_envvar_name}\\t{mount_point}\\text4\\trw,relatime\\t0\\t2\" >> /etc/fstab"
