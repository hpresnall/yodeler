"""Configuration for NAS server ."""
import util.shell as shell

from roles.role import Role

import util.file as file
import util.parse as parse


class Storage(Role):
    """Role that adds ZFS storage and Samba configuration."""

    def additional_packages(self) -> set[str]:
        return {"pciutils", "nvme-cli", "samba", "zfs"}

    def additional_configuration(self):
        if self._cfg["metrics"]:
            self._cfg["prometheus_collectors"].extend(["nvme", "samba"])

        self.add_alias("storage")
        self.add_alias("nas")
        self.add_alias("samba")
        self.add_alias("smb")

        parse.set_default_string("storage_dir", self._cfg, "/storage")
        parse.set_default_string("storage_user", self._cfg, "storage")
        parse.set_default_string("storage_group", self._cfg, "storage")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    def validate(self):
        _configure_storage(self._cfg)
        _configure_zfs(self._cfg)

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        storage_cfg = self._cfg["storage"]
        storage_dir = storage_cfg["base_dir"]

        # TODO check if exists
        setup.append(f"log \"Creating storage ZFS pool at {storage_dir}\"")
        zpool = "zpool create -o ashift=12 -O normalization=formD -O atime=off -o autotrim=on"
        zpool += " -O mountpoint=" + storage_dir
        zpool += " storage "
        zpool += self._cfg["zpool_vdev_type"] + " "

        for disk in self._cfg["disks"]:
            if disk["name"].startswith("storage"):
                zpool += disk["path"] + " "

        setup.append(zpool)

        group = storage_cfg["group"]
        setup.append(f"log \"Creating the group '{group}' & all share users\"")
        setup.append("addgroup -g 512 " + group)
        setup.append(f"adduser -D -S -s /sbin/nologin -h {storage_dir} -u 512 {group} {group}")
        setup.append(f"chown {group}:{group} {storage_dir}")
        setup.append("chmod 750 " + storage_dir)
        setup.blank()

        uid = 1024
        for user in storage_cfg["users"]:
            # need real users for samba; ensure they cannot log in & set home to storage_dir
            setup.append(f"adduser -D -s /sbin/nologin -h {storage_dir} -u {uid} {user['name']} {group}")
            uid += 1

        setup.blank()

        smb_conf = [file.substitute(self.name, "smb.conf", {
            "SITE_UPPER": self._cfg["site_name"].upper(),
            "SITE_DESC": self._cfg["site_name"] + " storage",
            "ALIASES": " ".join([a for a in self._cfg["aliases"] if a != "storage"]),
            "GROUP": group
        })]
        smb_conf.append("")

        for share in storage_cfg["shares"]:
            # note zfs syntax uses pool name as base
            # directories and samba use mountpoint
            path = share["path"]
            setup.append(f"zfs create storage/{path}")  # also creates directory
            if share["quota"] != "infinite":
                setup.append(f"zfs set quota={share['quota']} storage/{path}")

            path = storage_dir + "/" + path
            setup.append(f"chown {share['owner']}:{group} {path}")
            setup.append("chmod 750 " + path)
            setup.blank()

            smb_conf.append(f"[{share['name']}]")
            smb_conf.append("  path = " + path)

            if share["readers"]:
                readers = share["readers"]
                if "all" in readers:
                    smb_conf.append("  read list = " + "+" + group)
                else:
                    smb_conf.append("  read list = " + ", ".join([reader for reader in readers]))

            if share["writers"]:
                smb_conf.append("  write list = " + ", ".join([writer for writer in share["writers"]]))
                if len(share["writers"]) > 1:
                    smb_conf.append("  force user = " + share["owner"])
            else:
                smb_conf.append("  writable = no")

            if share["allow_guests"]:
                smb_conf.append("  guest ok = yes")

            smb_conf.append("")

        file.write("smb.conf", "\n".join(smb_conf), output_dir)

        setup.append("rootinstall smb.conf /etc/samba")
        setup.blank()

        setup.service("zfs-import", "boot")
        setup.service("zfs-mount", "boot")
        setup.service("samba")
        setup.blank()


def _configure_storage(cfg: dict):
    storage_loc = cfg["hostname"] + ".storage"
    storage = parse.non_empty_dict(storage_loc, cfg.get("storage"))

    base_dir = parse.set_default_string("base_dir", storage, "/storage")
    if not base_dir.startswith("/"):
        base_dir = "/" + base_dir

    invalid_names = {"root", "samba", "smb", "nobody", "wheel", "nfs"}

    group = parse.set_default_string("group", storage, "storage")
    if group in invalid_names:
        raise ValueError(f"{storage_loc} illegal group name '{group}'")

    location = storage_loc + ".users"
    names = {group}
    names.update(invalid_names)

    users = parse.non_empty_list(location, storage.get("users"))
    for i, user in enumerate(users, start=1):
        parse.non_empty_dict(location, user)

        u_loc = location + f"[{i}]"
        name = parse.non_empty_string("name", user, u_loc)

        if name in names:
            raise ValueError(f"{u_loc} duplicate or illegal username '{name}'")
        names.add(name)

        parse.non_empty_string("password", user, u_loc)

    location = storage_loc + ".shares"
    shares = parse.non_empty_list(location, storage.get("shares"))
    snames = set()
    spaths = set()

    for i, share in enumerate(shares, start=1):
        parse.non_empty_dict(location, share)

        s_loc = location + f"[{i}]"

        name = parse.non_empty_string("name", share, s_loc)
        if name in snames:
            raise ValueError(f"{s_loc} duplicate share name '{name}'")
        snames.add(name)

        # optional path; will be relative to base_dir
        path = parse.set_default_string("path", share, name.lower().replace(" ", "_"))
        if "/" in path:
            raise ValueError(f"{s_loc} share path '{path}' cannot contain '/'")
        if path in spaths:
            raise ValueError(f"{s_loc} duplicate share path '{path}'")
        spaths.add(name)

        share["path"] = path

        share["writers"] = writers = parse.read_string_list_plurals({"writer", "writers"}, share, s_loc)
        share.pop("writer", None)
        for w, writer in enumerate(writers, start=1):
            if writer not in names:
                raise ValueError(f"{s_loc}.writer[{w}] '{writer}' not in list of storage users")
        # empty writers => read only = yes

        # TODO if group is in readers or writers that should also mean all
        share["readers"] = readers = parse.read_string_list_plurals({"reader", "readers"}, share, s_loc)
        share.pop("reader", None)
        # TODO readers defaults to all if writers is empty
        if "all" in readers:
            readers = ["all"]
        else:
            for r, reader in enumerate(readers, start=1):
                # all => storage group can read
                if reader not in names:
                    raise ValueError(f"{s_loc}.reader[{r}] '{reader}' not in list of storage users")
        # empty readers => only read+write users

        if not readers and not writers:
            raise ValueError(f"{s_loc} must set at least 1 reader or writer")

        parse.set_default_string("quota", share, "infinite")

        # TODO change owner to default_user; if None, do not set force user in smb
        # do not set if length is 1 or set to the first writer
        if writers:
            # default to the first writer being the owner
            owner = parse.set_default_string("owner", share, writers[0])
            if (owner not in names):
                raise ValueError(f"{s_loc}.owner '{owner}' not in list of storage users")
        else:
            # just readers, set owner to base storage user
            parse.set_default_string("owner", share, group)

        share.setdefault("allow_guests", False)


def _configure_zfs(cfg: dict):
    storage_disks = []

    for disk in cfg["disks"]:
        if disk["name"].startswith("storage"):
            storage_disks.append(disk)

    zpool_vdev_type = cfg.get("zpool_vdev_type", None)

    if zpool_vdev_type:
        valid_types = ["mirror", "raidz", "raidz1", "raidz2", "raidz3", "draid", "draid1", "draid2", "draid3"]
        if zpool_vdev_type not in valid_types:
            raise ValueError(f"invalid zpool_vdev_type, must be one of {valid_types}")
        return  # no validation, assume user knows what they are doing

    num_disks = len(storage_disks)

    if num_disks == 1:
        zpool_vdev_type = ""  # just the plain disk
    elif num_disks == 2:
        zpool_vdev_type = "mirror"
    else:
        zpool_vdev_type = "raidz"

    cfg["zpool_vdev_type"] = zpool_vdev_type
