"""Configuration for NAS server ."""
import util.shell as shell

from roles.role import Role

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

        zpool = "zpool create -o ashift=12 -O normalization=formD -O atime=off -o autotrim=on"
        zpool += " -O mountpoint=" + storage_dir
        zpool += " storage "
        zpool += self._cfg["zpool_vdev_type"] + " "

        for disk in self._cfg["disks"]:
            if disk["name"].startswith("storage"):
                zpool += disk["name"] + " "

        setup.comment("create the ZFS volume for storage")
        setup.append(zpool)
        setup.append(f"chown {self._cfg['storage_dir']}:{self._cfg['storage_group']} {storage_dir}")
        setup.append(f"chmod 750 {storage_dir}")
        setup.blank()

        # TODO create group and users
        setup.comment("create the storage group & users")
        setup.append("group add " + storage_cfg["group"])
        for user in storage_cfg["users"]:
            setup.append("user")

        # TODO create all shares
        # chown and chmod as necesary
        # add quote if not 'infinite'
        # chown if only 1 writer, that writer owns dir
        # if no writers => storage owns
        # apply quota

        # TODO create smb.conf

        setup.service("zfs-import", "boot")
        setup.service("zfs-mount", "boot")
        setup.service("samba")
        setup.blank()


def _configure_storage(cfg: dict):
    storage_loc = cfg["hostname"] + ".storage"
    storage = parse.non_empty_dict(storage_loc, cfg.get("storage"))

    parse.set_default_string("base_dir", storage, "/storage")
    parse.set_default_string("group", storage, "storage")

    location = storage_loc + ".users"
    users = parse.non_empty_list(location, storage.get("users"))
    names = {"storage", "samba", "smb", "nobody"}

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

        if path in spaths:
            raise ValueError(f"{s_loc} duplicate share path '{path}'")
        spaths.add(name)

        writers = parse.read_string_list_plurals({"writer", "writers"}, share, s_loc)
        share.pop("writer", None)
        for w, writer in enumerate(writers, start=1):
            if writer not in names:
                raise ValueError(f"{s_loc}.writer[{w}] '{writer}' not in list of storage users")
        # empty writers => read only = yes

        readers = parse.read_string_list_plurals({"reader", "readers"}, share, s_loc)
        share.pop("reader", None)
        for r, reader in enumerate(readers, start=1):
            # all => storage group can read
            if (reader != "all") and (reader not in names):
                raise ValueError(f"{s_loc}.reader[{r}] '{reader}' not in list of storage users")
        # empty readers => only read+write users

        if not readers and not writers:
            raise ValueError(f"{s_loc} must set at least 1 reader or writer")

        parse.set_default_string("quota", share, "infinite")
        write_as = parse.set_default_string("write_as", share, "nobody")

        if (write_as != "nobody") and (write_as not in names):
            raise ValueError(f"{s_loc}.write_as '{write_as}' not in list of storage users")

        if not writers:
            share["write_as"] = "nobody"  # overwrite if no writers


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
