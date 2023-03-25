import sys

from roles.role import Role

import util.shell as shell


class Test(Role):
    """Role for testing that does not do any additional configuration."""

    def additional_packages(self) -> set[str]:
        return set()

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return sys.maxsize

    def validate(self):
        pass

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        pass
