"""Configuration for ZFS based NAS server running Samba."""
import util.file as file
import util.parse as parse

import script.shell as shell

from role.roles import Role


class Storage(Role):
    """Role that adds ZFS storage and Samba configuration."""

    def additional_packages(self) -> set[str]:
        return {"pciutils", "nvme-cli", "samba", "zfs"}

    def additional_aliases(self) -> list[str]:
        return ["storage", "nas", "samba", "smb"]

    def additional_configuration(self):
        parse.set_default_string("storage_dir", self._cfg, "/storage")
        parse.set_default_string("storage_user", self._cfg, "storage")
        parse.set_default_string("storage_group", self._cfg, "storage")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    def validate(self):
        _validate_storage(self._cfg)
        _configure_zfs(self._cfg)

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        storage_cfg = self._cfg["storage"]
        storage_dir = storage_cfg["base_dir"]

        # zpools cannot be created inside chroot; do everything in the top-level yodel.sh
        before_chroot = self._cfg["unnested_before_chroot"]
        before_chroot.append("log \"Installing & starting ZFS kernel module\"")
        before_chroot.append("apk -q --no-progress add zfs losetup")
        before_chroot.append("modprobe zfs")
        before_chroot.append("")
        before_chroot.append("log \"Loop mounting storage disks for zpool configuration\"")
        before_chroot.append("")

        image_disks_count = 1

        # creating zfs outside the VM which also creates all the share dirs
        # instead of setting perms during setup, create a script that runs on first boot using the 'local' service
        local = shell.ShellScript("storage_perms.start", False)
        local.comment("ensure pool is imported")
        local.append("zpool import storage")
        local.blank()
        local.comment("update storage & share permissions")
        local.comment("change file permissions even if group or user already existed")
        local.blank()

        # build zpool command with all the storage disks
        zpool = "  zpool create -o ashift=12 -O normalization=formD -O atime=off -o autotrim=on"
        zpool += " -O mountpoint=" + storage_dir
        zpool += " storage "
        zpool += self._cfg["zpool_vdev_type"] + " "

        for disk in self._cfg["disks"]:
            if disk["name"].startswith("storage"):
                # creating zpool outside of vm, so use vm host's path
                path = disk["host_path"]

                if disk["type"] == "img":
                    # mount / unmount image disks
                    # use loop mount rather than the raw disk image; set envvar on mount, use that for unmount
                    # zfs treats images differently and importing them into the vm does not work
                    before_chroot.append(f"STORAGE{image_disks_count}=$(losetup  --find --show {path})")
                    self._cfg["unnested_after_chroot"].append(f"losetup --detach $STORAGE{image_disks_count}")
                    zpool += "$STORAGE" + str(image_disks_count) + " "
                    image_disks_count += 1
                else:
                    zpool += path + " "

        if image_disks_count > 1:
            before_chroot.append("")
            before_chroot.append("# output for logs")
            before_chroot.append("losetup --all --list")
            before_chroot.append("")

        before_chroot.append("zpool import 2>&1 | grep storage &>/dev/null && ret=$? || ret=$?")
        before_chroot.append("if [ $ret -eq 0 ]; then")
        before_chroot.append(f"  log \"Importing existing ZFS storage pool to {storage_dir}\"")
        before_chroot.append("  zpool import storage")
        before_chroot.append("else")
        before_chroot.append(f"  log \"Creating ZFS storage pool at '{storage_dir}'\"")
        before_chroot.append(zpool.strip())
        before_chroot.append("fi")
        before_chroot.append("")

        group = storage_cfg["group"]
        setup.log(f"Creating group '{group}' & all share users")

        setup.append(f"id \"{group}\" &>/dev/null && ret=$? || ret=$?")
        setup.append(f"if [ $ret -ne 0 ]; then")
        setup.append("  addgroup -g 1024 " + group)
        setup.append(f"  adduser -D -s /sbin/nologin -h {storage_dir} -g storage -G {group} -u 1024 {group}")
        setup.append("fi")
        setup.blank()

        # start user ids at 2048
        uid = 2048

        for user in storage_cfg["users"]:
            name = user["name"]
            pwd = user["password"]

            # need real users for samba; ensure they cannot log in & set home to storage_dir
            setup.append(f"id \"{name}\" &>/dev/null && ret=$? || ret=$?")
            setup.append(f"if [ $ret -ne 0 ]; then")
            setup.append(f"  adduser -D -s /sbin/nologin -h {storage_dir} -g storage -G {group} -u {uid} {name}")
            setup.append(f"  echo -e \"{pwd}\\n{pwd}\\n\" | pdbedit -a -t -u {name}")
            setup.append("fi")
            setup.blank()
            uid += 1

        local.append(f"chown {group}:{group} {storage_dir}")
        local.append("chmod 770 " + storage_dir)
        local.blank()

        # create base samba config, then add all the shares
        smb_conf = [file.substitute(self.name, "smb.conf", {
            "HOSTNAME": self._cfg["hostname"],
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

            # if owner of the path is explicitly set use it
            # otherwise, use the only writer or the group's user
            owner = share['owner']
            perm = 750
            if not owner:
                if len(share["writers"]) == 1:
                    owner = share["writers"][0]
                else:
                    owner = group
                    if writers:  # more than 1 writer => entire group needs write access
                        perm = 770
                    # otherwise, only readers; leave at 750

            before_chroot.append(f"if [ ! -e \"{os_path}\" ]; then")
            before_chroot.append(f"  log \"Creating share '{path}'\"")
            before_chroot.append(f"  zfs create storage/{path}")  # also creates directory
            before_chroot.append("else")
            before_chroot.append(f"  log \"Using existing share '{path}'\"")
            before_chroot.append("fi")
            if share["quota"] != "infinite":
                before_chroot.append(f"zfs set quota={share['quota']} storage/{path}")
            before_chroot.append("")

            local.append(f"chown {owner}:{group} {os_path}")
            local.append(f"chmod {perm} {os_path}")
            local.blank()

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
        # end for all shares

        smb_conf.append("")
        file.write("smb.conf", "\n".join(smb_conf), output_dir)

        self._cfg["unnested_after_chroot"].append("zpool export storage")
        self._cfg["unnested_after_chroot"].append("modprobe -r zfs")
        self._cfg["unnested_after_chroot"].append("apk -q del zfs losetup")

        setup.append("rootinstall $DIR/smb.conf /etc/samba")
        setup.blank()

        setup.service("zfs-import", "boot")
        setup.service("zfs-mount", "boot")
        setup.service("samba")
        setup.service("local")
        setup.blank()

        setup.comment("scrub the storage pool once a week")
        setup.append("echo -e \"#!/bin/sh\nzpool scrub storage\n\" > /etc/periodic/weekly/zfs_scrub")
        setup.append("chmod 755 /etc/periodic/weekly/zfs_scrub")
        setup.blank()

        setup.comment("configure storage permissions on first boot")
        setup.append("install -o root -g root -m 750 storage_perms.start /etc/local.d")
        setup.blank()

        setup.comment("do not run netbios")
        setup.append("echo \'daemon_list=\"smbd\"' >> /etc/conf.d/samba")

        local.comment("only run once")
        local.append("mv /etc/local.d/storage_perms.start /etc/local.d/storage_perms.done")
        local.blank()
        local.write_file(output_dir)


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
    invalid_names.add(group)  # cannot add group name as a user
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
            disk["format"] = False  # zfs will format

    num_disks = len(storage_disks)

    if num_disks == 0:
        raise ValueError("no 'disks' named 'storage*' defined for " + cfg["hostname"])

    # if set, ensure valid zpool type
    zpool_vdev_type = cfg.get("zpool_vdev_type", None)

    if zpool_vdev_type:
        valid_types = ["mirror", "raidz", "raidz1", "raidz2", "raidz3", "draid", "draid1", "draid2", "draid3"]
        if zpool_vdev_type not in valid_types:
            raise ValueError(f"invalid zpool_vdev_type, must be one of {valid_types}")
    else:  # set default values based on the number of disks
        if num_disks == 1:
            zpool_vdev_type = ""  # just the plain disk
        elif num_disks == 2:
            zpool_vdev_type = "mirror"
        else:
            zpool_vdev_type = "raidz"

    cfg["zpool_vdev_type"] = zpool_vdev_type
