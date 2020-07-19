import os
import stat

import util.file


class ShellScript():
    name = ""
    _script_fragments = []

    def __init__(self, name):
        if (name is None) or (name == ""):
            raise ValueError("name cannot be None or empty")

        self.name = name

        shell_header = """#!/bin/sh\n"""

        self._script_fragments = [shell_header]

    def append(self, fragment):
        self._script_fragments.append(fragment)

    def append_file(self, path):
        self._script_fragments.append(util.file.read(path))

    def append_self_dir(self):
        self._script_fragments.append("""DIR=$(cd -P -- "$(dirname -- "$0")" && pwd -P)\n""")

    def append_rootinstall(self):
        self._script_fragments.append("""rootinstall()
{
  install -o root -g root -m 644 $@
}
""")

    def setup_logging(self, hostname):
        self.append("mkdir -p  /root/yodeler/logs")
        self.append("exec >> /root/yodeler/logs/" + hostname + " 2>&1")
        self.append("")

    def write_file(self, dir):
        path = os.path.join(dir, self.name)
        # ensure final blank line
        if not self._script_fragments[-1] == "":
            self._script_fragments.append("")
        script = "\n".join(self._script_fragments)
        util.file.write(path, script)
        os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
