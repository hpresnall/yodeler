"""Configuration for an XFCE host."""
import sys

import util.shell as shell
import util.disk as disk

from roles.role import Role

import util.parse as parse


class Build(Role):
    """Role that adds common build tools and compilers."""

    def additional_packages(self) -> set[str]:
        packages = {"build-base", "automake", "autoconf", "make", "pkgconf", "git", "gcc", "python3", "py3-pip", "perl"}

        if self._cfg.setdefault("java", False) == True:
            packages.add("openjdk19-jdk")
        if self._cfg.setdefault("java17", False) == True:
            packages.add("openjdk17-jdk")
        if self._cfg.setdefault("java11", False) == True:
            packages.add("openjdk11-jdk")

        if self._cfg.setdefault("go", False) == True:
            packages.add("go")

        return packages

    def additional_configuration(self):
        if self._cfg["is_vm"]:
            # add an additional disk for builds so it can be persistent across VM instances
            # create & format the image before running setup.sh in chroot
            disk_path = self._cfg["vm_images_path"] + "/" + self._cfg["hostname"] + "_build.img"
            size = self._cfg.setdefault("build_disk_size_mb", 128)

            self._cfg["vm_disk_paths"].append(disk_path)

            self._cfg["before_chroot"] = "log \"Setting up build disk image\"\n" + \
                disk.create_disk_image(self._cfg['hostname'], disk_path, size, "BUILD_UUID")
        elif "build_dev" in self._cfg:
            # optionally use another disk on physcial servers
            # if not set, a plain /build directory will be created instead
            build_dev = parse.non_empty_string("build_dev", self._cfg, self._cfg["hostname"])

            if build_dev == self._cfg["root_dev"]:
                raise ValueError(
                    f"build_dev={build_dev} cannot be the same as the system install location specified by 'root_dev'")

            self._cfg["before_chroot"] = "log \"Setting up build disk image\"\n" + \
                disk.format_disk(self._cfg["hostname"], build_dev, "BUILD_UUID")

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    def validate(self):
        if self._cfg["is_vm"] and (self._cfg["disk_size_mb"] < 1024):
            raise ValueError("build server must set 'disk_size_mb' to at least 1,024")

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        user = self._cfg["user"]

        if self._cfg["is_vm"]:
            setup.append(disk.create_fstab_entry("BUILD_UUID", "/build"))
        elif "build_dev" in self._cfg:
            setup.append(disk.create_fstab_entry("BUILD_UUID", "/build"))

        setup.append("mkdir /build")
        setup.append(f"chown {user}:{user} /build")
        setup.append("chmod 750 /build")
