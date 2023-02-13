"""Utility for creating shell scripts."""
import os
import stat

import util.file


class ShellScript():
    """ShellScript encapsulates a single, named shell script.
    Scripts can have code and comments appended and then the script can be output to the filesystem when complete.
    """
    name = ""
    _script_fragments = []

    def __init__(self, name):
        if not name:
            raise ValueError("name cannot be None or empty")

        self.name = name

        shell_header = "#!/bin/sh\nset -o errexit\n"

        self._script_fragments = [shell_header]

    def blank(self):
        """Add a blank line to the script."""
        self.append("")

    def comment(self, comment):
        """Add a comment to the script."""
        self.append("# " + comment)

    def append(self, fragment):
        """Add code to the script."""
        self._script_fragments.append(fragment)

    def substitute(self, file, cfg):
        """Append the given template file to the script, after performing variable substitution."""
        self.append(util.file.substitute(file, cfg))

    def append_self_dir(self):
        """Append code that puts the directory where this shell script is located into the $DIR variable.
        Also sets $SITE_DIR based on that location."""
        self.append("""DIR=$(cd -P -- "$(dirname -- "$0")" && pwd -P)""")
        self.append("SITE_DIR=$(realpath $DIR/..)")
        self.blank()

    def append_rootinstall(self):
        """Append a rootinstall shell function.
        This ensures the install command copies as root with 644 perms."""
        self.append("""rootinstall() {
  install -o root -g root -m 644 $@
}
""")

    def service(self, service: str, runlevel: str = "default"):
        """Adds a service to system startup at the given runlevel."""
        self.append(f"rc-update add {service} {runlevel}")

    def setup_logging(self, hostname: str):
        """Make this script log to $SITE_DIR/logs/<yyyymmdd>_<hhmmss>/<hostname>.log.
        This removes to need to explicitly redirect all commands in the script.
        All scripts should use the log() function rather than echo."""
        self.comment("configure logging")
        self.append("LOG_DIR=$SITE_DIR/logs/$(date +\"%Y%m%d_%H%M%S\")")
        self.append("mkdir -p  \"$LOG_DIR\"")
        self.append(f"LOG=$LOG_DIR/{hostname}")
        self.append("""if [ -t 3 ]; then
  # for chroot and subshells, continue using parent's stdout at fd 3
  :
else
  exec 3>&1
fi""")
        self.append("echo \"Writing logs to $LOG\" >&3")
        self.append("exec 1> $LOG")
        self.append("exec 2>&1")
        self.blank()
        self.add_log_function()

    def add_log_function(self):
        self.append("""
log () {
  echo $*
  echo $* >&3
}
""")

    def write_file(self, output_dir):
        """Write the script to the given directory."""
        path = os.path.join(output_dir, self.name)
        # ensure final blank line
        if self._script_fragments[-1]:
            self._script_fragments.append("")
        script = "\n".join(self._script_fragments)
        util.file.write(path, script)
        os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
