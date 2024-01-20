"""Configuration for host with standard build & compile tools."""
import util.shell as shell

from roles.role import Role

import util.parse as parse


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

    def additional_configuration(self):
        self._cfg["build_dir"] = "/build"

        # optional disk for builds, if defined
        # otherwise just use a directory on the system disk
        for disk in self._cfg["disks"]:
            if disk["name"] == "build":
                self._cfg["build_dir"] = parse.set_default_string("mountpoint", disk, "/build")
                break

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    def validate(self):
        if self._cfg["is_vm"] and (self._cfg["disk_size_mb"] < 1024):
            raise ValueError("build server must set 'disk_size_mb' to at least 1,024")

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        build_dir = self._cfg["build_dir"]

        user = self._cfg["user"]
        setup.append(f"mkdir {build_dir}")
        setup.append(f"chown {user}:{user} {build_dir}")
        setup.append(f"chmod 750 {build_dir}")
