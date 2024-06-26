"""Configuration for an XFCE host."""
from role.roles import Role

import sys

import script.shell as shell


class XWindows(Role):
    """XWindows setup for XFCE."""

    def additional_packages(self) -> set[str]:
        packages = {"xorg-server", "xf86-input-libinput", "eudev", "udev-init-scripts", "udev-init-scripts-openrc",
                    "mesa-dri-gallium", "consolekit2", "gvfs", "gvfs-smb", "udisks2", "lightdm", "lightdm-gtk-greeter", "polkit",
                    "xfce4", "xfce4-session", "xfce4-terminal", "xfce4-screensaver", "xfce4-taskmanager", "xfce4-cpugraph-plugin",
                    "firefox", "mousepad"}

        if "vmhost" in [role.name for role in self._cfg["roles"]]:
            packages.add("virt-manager")

        return packages

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return sys.maxsize

    def validate(self):
        if self._cfg["is_vm"]:
            raise ValueError("XWindows cannot be installed on VMs")

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        user = self._cfg["user"]

        # mimic Alpine setup-xorg-base & setup-devd scripts to avoid adding additional repo & apk update
        # community repo is required in config!
        setup.append("# mimic setup-org-base & setup-desktop xfce")
        setup.append("rc-update -q delete mdev sysinit")
        setup.service("udev", "sysinit")
        setup.service("udev-trigger", "sysinit")
        setup.service("udev-settle", "sysinit")
        setup.service("udev-postmount")
        setup.service("lightdm")
        setup.append(f"addgroup {user} audio")
        setup.append(f"addgroup {user} video")
        setup.append(f"addgroup {user} netdev")
