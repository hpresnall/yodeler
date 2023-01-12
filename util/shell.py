"""Utility for creating shell scripts."""
import os
import stat

import util.file


class ShellScript():
    """ShellScript encapsulates a single, named shell script.
    Scripts can have code appended and then output to the filesystem when complete.
    """
    name = ""
    _script_fragments = []

    def __init__(self, name):
        if not name:
            raise ValueError("name cannot be None or empty")

        self.name = name

        shell_header = """#!/bin/sh\nset -o errexit\n"""

        self._script_fragments = [shell_header]

    def append(self, fragment):
        """Add code to the script."""
        self._script_fragments.append(fragment)

    def substitute(self, file, cfg):
        """Append the given template file to the script, after performing variable substitution."""
        self._script_fragments.append(util.file.substitute(file, cfg))

    def append_self_dir(self):
        """Append code that puts the directory where the shell is located into the $DIR variable."""
        self._script_fragments.append("""DIR=$(cd -P -- "$(dirname -- "$0")" && pwd -P)\n""")

    def append_rootinstall(self):
        """Append a rootinstall shell function.
        This ensures the install command copies as root with 644 perms."""
        self._script_fragments.append("""rootinstall()
{
  install -o root -g root -m 644 $@
}
""")

    def setup_logging(self, hostname):
        """Make this script log to /root/yodeler/logs/<hostname>.
        This removes to need to explicitly redirect all commands in the script."""
        self.append("mkdir -p  /root/yodeler/logs")
        self.append("exec >> /root/yodeler/logs/" + hostname + " 2>&1")
        self.append("")

    def write_file(self, output_dir):
        """Write the script to the given directory."""
        path = os.path.join(output_dir, self.name)
        # ensure final blank line
        if self._script_fragments[-1]:
            self._script_fragments.append("")
        script = "\n".join(self._script_fragments)
        util.file.write(path, script)
        os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
