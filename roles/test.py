import sys

from roles.role import Role

import util.shell as shell


class Test(Role):
    """Role for testing that does not do any additional configuration."""

    def __init__(self, cfg: dict):
        super().__init__("test", cfg)

    def additional_packages(self) -> set[str]:
        return set()

    def write_config(self, setup: shell.ShellScript, output_dir: str):
        pass

    def validate(self):
        return super().validate()

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        return 0

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        return sys.maxsize
