import util.shell

from roles.role import Role

class FakeISP(Role):
    def additional_packages(self) -> set[str]:
        return set()

    def validate(self):
        pass

    def write_config(self, setup: util.shell.ShellScript, output_dir: str):
        pass

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
       return 0