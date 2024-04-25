"""Configuration for server with standard build & compile tools."""
from role.roles import Role

import util.parse as parse

import script.shell as shell


class Build(Role):
    """Role that adds common build tools and compilers."""

    def additional_packages(self) -> set[str]:
        packages = {"build-base", "automake", "autoconf", "make", "pkgconf", "git", "gcc", "python3", "py3-pip", "perl"}

        if self._cfg.setdefault("java", False):
            packages.add("openjdk19-jdk")
        if self._cfg.setdefault("java17", False):
            packages.add("openjdk17-jdk")
        if self._cfg.setdefault("java11", False):
            packages.add("openjdk11-jdk")

        if self._cfg.setdefault("go", False):
            packages.add("go")

        return packages

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    def validate(self):
        if self._cfg["is_vm"] and (self._cfg["disk_size_mb"] < 2048):
            raise ValueError("build server must set 'disk_size_mb' to at least 2,048")

        # optional disk for builds, if defined
        build_disk = None

        for disk in self._cfg["disks"]:
            if disk["name"] == "build":
                build_disk = disk
                # = parse.set_default_string("mountpoint", disk, "/build")
                break

        if build_disk:
            mountpoint = disk.get("mountpoint", None)

            if mountpoint:
                build_dir = self._cfg.get("build_dir", None)

                # both build and mount point set => override mount point with build_dir
                if build_dir:
                    disk["mountpoint"] = build_dir
                else:  # set the build_dir to the mount point
                    parse.set_default_string("build_dir", self._cfg, mountpoint)
            else:
                # no mount point, set both to the build_dir
                build_dir = parse.set_default_string("build_dir", self._cfg, "/build")
                disk["mountpoint"] = build_dir
        else:
            # no disk; just use /build on the system disk
            build_dir = parse.set_default_string("build_dir", self._cfg, "/build")

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        build_dir = self._cfg["build_dir"]

        user = self._cfg["user"]
        setup.append(f"mkdir -p {build_dir}")
        setup.append(f"chown {user}:{user} {build_dir}")
        setup.append(f"chmod 750 {build_dir}")
