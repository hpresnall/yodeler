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

        self._cfg["before_chroot"] = ["apk add zfs", "modprobe zfs"]
        self._cfg["after_chroot"] = ["modprobe -r zfs", "apk del zfs"]

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    def validate(self):
        _validate_storage(self._cfg)
        _configure_zfs(self._cfg)

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        storage_cfg = self._cfg["storage"]
        storage_dir = storage_cfg["base_dir"]

        zpool = "  zpool create -o ashift=12 -O normalization=formD -O atime=off -o autotrim=on"
        zpool += " -O mountpoint=" + storage_dir
        zpool += " storage "
        zpool += self._cfg["zpool_vdev_type"] + " "

        for disk in self._cfg["disks"]:
            if disk["name"].startswith("storage"):
                zpool += disk["path"] + " "

        setup.append("zpool import 2>&1 | grep storage &>/dev/null && ret=$? || ret=$?")
        setup.append("if [ $ret -eq 0 ]; then")
        setup.log(f"Importing existing ZFS storage pool to {storage_dir}", indent="  ")
        setup.append("  zpool import storage")
        setup.append("else")
        setup.log(f"Creating ZFS storage pool at {storage_dir}", indent="  ")
        setup.append(zpool)
        setup.append("fi")
        setup.blank()

        group = storage_cfg["group"]
        setup.log(f"Creating group '{group}' & all share users")
        setup.blank()

        setup.comment("change file permissions even if group or user already existed")
        setup.append(f"id \"{group}\" &>/dev/null && ret=$? || ret=$?")
        setup.append(f"if [ $ret -ne 0 ]; then")
        setup.append("  addgroup -g 512 " + group)
        setup.append(f"  adduser -D -S -s /sbin/nologin -h {storage_dir}  -g storage -G {group} -u 512 {group}")
        setup.append("fi")
        setup.blank()

        uid = 1024
        for user in storage_cfg["users"]:
            name = user["name"]
            pwd = user["password"]

            # need real users for samba; ensure they cannot log in & set home to storage_dir
            setup.append(f"id \"{name}\" &>/dev/null && ret=$? || ret=$?")
            setup.append(f"if [ $ret -ne 0 ]; then")
            setup.append(f"  adduser -D -s /sbin/nologin -h {storage_dir} -g storage -G {group} -u {uid} {name}")
            setup.append(f"  echo -e \"{pwd}\\n{pwd}\\n\" | smbpasswd -a -s {name}")
            setup.append("fi")
            setup.blank()
            uid += 1

        setup.comment("update base storage dir after users since users share that home dir and adduser updates the perms")
        setup.append(f"chown {group}:{group} {storage_dir}")
        setup.append("chmod 750 " + storage_dir)
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

            os_path = storage_dir + "/" + path
            # owner of the path is explicitly set, the only writer or the group's user
            owner = share['owner']
            if not owner:
                if len(share["writers"]) == 1:
                    owner = share["writers"][0]
                else:
                    owner = group

            setup.append(f"if [ ! -e \"{os_path}\" ]; then")
            setup.log(f"Creating share '{path}'", indent="  ")
            setup.append(f"  zfs create storage/{path}")  # also creates directory
            setup.append("else")
            setup.log(f"Using existing share '{path}'", indent="  ")
            setup.append("fi")
            setup.blank()

            if share["quota"] != "infinite":
                setup.append(f"zfs set quota={share['quota']} storage/{path}")
            setup.append(f"chown {owner}:{group} {os_path}")
            setup.append("chmod 750 " + os_path)
            setup.blank()

            smb_conf.append(f"[{share['name']}]")
            smb_conf.append("  path = " + os_path)

            if share["readers"]:
                readers = share["readers"]
                if readers[0] == group:
                    smb_conf.append("  read list = " + "+" + group)
                else:
                    smb_conf.append("  read list = " + ", ".join(readers))

            if share["writers"]:
                writers = share["writers"]
                if writers[0] == group:
                    smb_conf.append("  write list = " + "+" + group)
                else:
                    smb_conf.append("  write list = " + ", ".join(writers))

                # if no owner is set, let samba set the owner to the connected user
                # group perms for new files will still be set to group readable due to create/directory mask in smb.conf
                if share["owner"]:
                    smb_conf.append("  force user = " + share["owner"])
            else:
                smb_conf.append("  writable = no")

            if share["allow_guests"]:
                smb_conf.append("  guest ok = yes")

            smb_conf.append("")

        smb_conf.append("")
        file.write("smb.conf", "\n".join(smb_conf), output_dir)

        setup.append("rootinstall smb.conf /etc/samba")
        setup.blank()

        setup.service("zfs-import", "boot")
        setup.service("zfs-mount", "boot")
        setup.service("samba")
        setup.blank()


def _validate_storage(cfg: dict):
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
    invalid_names.add("group")  # cannot add group name as a user
    user_names = set()

    users = parse.non_empty_list(location, storage.get("users"))
    for i, user in enumerate(users, start=1):
        parse.non_empty_dict(location, user)

        u_loc = location + f"[{i}]"
        name = parse.non_empty_string("name", user, u_loc)

        if name in invalid_names:
            raise ValueError(f"{u_loc} duplicate or illegal username '{name}'")
        # ensure no duplicate names; track user names for use in shares
        invalid_names.add(name)
        user_names.add(name)

        parse.non_empty_string("password", user, u_loc)

    location = storage_loc + ".shares"
    shares = parse.non_empty_list(location, storage.get("shares"))
    share_names = set()
    share_paths = set()

    for i, share in enumerate(shares, start=1):
        parse.non_empty_dict(location, share)

        s_loc = location + f"[{i}]"

        name = parse.non_empty_string("name", share, s_loc)
        if name in share_names:
            raise ValueError(f"{s_loc} duplicate share name '{name}'")
        share_names.add(name)

        # optional path; defaults to lowercase share name with substitutions
        # will be relative to base_dir
        path = parse.set_default_string("path", share, name.lower().replace(" ", "_"))
        if "/" in path:
            raise ValueError(f"{s_loc} share path '{path}' cannot contain '/'")
        if path in share_paths:
            raise ValueError(f"{s_loc} duplicate share path '{path}'")
        share_paths.add(name)

        share["path"] = path

        # empty writers => read only; readers must have at least one user
        # empty readers => only read+write users
        writers = _get_user_list(share, "writer", group, user_names, s_loc)
        readers = _get_user_list(share, "reader", group, user_names, s_loc)

        if not readers and not writers:
            raise ValueError(f"{s_loc} must set at least 1 reader or writer")

        # no need for readers list if writers is the same
        if readers == writers:
            share["readers"] = []
        else:
            # if a user is a writer, it does not need to be in the readers list
            share["readers"] = list(readers - writers)
        share["writers"] = list(writers)

        parse.set_default_string("quota", share, "infinite")

        owner = share.setdefault("owner", None)
        if owner:
            if not isinstance(owner, str):
                raise ValueError(f"{s_loc}.owner '{owner}' must be a string")
            if (owner not in user_names):
                raise ValueError(f"{s_loc}.owner '{owner}' not in list of storage users")
            if (owner not in writers):
                raise ValueError(f"{s_loc}.owner '{owner}' not in list of writers for the share")

        share.setdefault("allow_guests", False)


def _get_user_list(share: dict, type: str, group: str, user_names: set, location: str) -> set:
    plural = type + 's'
    user_list = parse.read_string_list_plurals({type, plural}, share, location)
    share.pop(type, None)  # remove singular; caller must ensure plural is set to this function's return value

    for i, user in enumerate(user_list, start=1):
        if user == group:  # no need for any other writers
            user_list = [group]
            break
        if user not in user_names:
            raise ValueError(f"{location}.{type}[{i}] '{user}' not in list of storage users")

    user_set = set(user_list)

    # all users, just use the group name
    if user_set == user_names:
        share[type] = [group]
        user_set = {group}

    return user_set


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
