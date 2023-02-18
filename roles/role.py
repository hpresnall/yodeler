"""Defines the abstract Role class.
A role represents various configurations that can be applied to a host to implement a specific functionality."""
import importlib
import inspect

from abc import ABC, abstractmethod

import util.shell as shell


class Role(ABC):
    """Role is the abstract base class that defines how to configure a specific set of
    functionality on a server.
    """

    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self._cfg = cfg

    @abstractmethod
    def additional_packages(self) -> set[str]:
        """The packages needed to implement this role."""

    def configure_interfaces(self):
        """Add any additional interfaces for the role.
        Interface validation will be run afer all roles have this function called."""

    def additional_configuration(self):
        """Add any additional default configuration & run validation specific to this role.
        This is run after configure_interfaces()."""

    @staticmethod
    def minimum_instances(site_cfg: dict) -> int:
        """What is the minimum number of hosts that can have this role for a single site?"""
        # default to required
        return 1

    @staticmethod
    def maximum_instances(site_cfg: dict) -> int:
        """What is the maximum number of hosts that can have this role for a single site?"""
        # default to a single instance
        return 1

    @abstractmethod
    def validate(self):
        """Run any additional validation needed for this role.

        This will be called before write_config(). All hosts for the site will be loaded so the total site
        layout can be checked, if needed."""

    @abstractmethod
    def write_config(self, setup: shell.ShellScript, output_dir: str):
        """Write any necessary shell script commands to setup.
        Create the configuration files that implement this role.
        """

    def add_alias(self, alias: str):
        """Add an alias to the host.

        The alias will be numbered if other hosts in the site have the same role"""
        self._cfg["aliases"].add(alias)

        # assume this is called _after_ _load_roles() and will not raise KeyError
        existing_hosts = self._cfg["roles_to_hostnames"][self.name]

        # only instance of the role, do not rename
        if len(existing_hosts) == 1:
            return

        # rename all aliases by renumbering
        for i, host in enumerate(existing_hosts, start=1):
            aliases = self._cfg["hosts"][host]["aliases"]
            aliases.discard(alias)
            aliases.add(alias + str(i))


# cache loaded Role subclasses
_role_class_by_name = {}


def load(role_name: str, host_cfg: dict) -> Role:
    """Load an Role subclass instance using the given role name."""
    clazz = _role_class_by_name.setdefault(role_name, _load_role_class(role_name))

    # instantiate the class
    try:
        return clazz(host_cfg)
    except TypeError as te:
        raise KeyError(f"cannot instantiate class '{clazz}'") from te


def _load_role_class(role_name: str):
    try:
        mod = importlib.import_module("roles." + role_name)
    except ModuleNotFoundError as mnfe:
        raise KeyError(f"cannot load module for role '{role_name}' from the roles package") from mnfe

    # find class for role; assume only 1 class in each module
    role_class = None

    for clazz in inspect.getmembers(mod, inspect.isclass):
        if clazz[0].lower() == role_name.lower():
            role_class = clazz[1]
            break

    if role_class is None:
        raise KeyError(f"cannot find class for role '{role_name}' in module '{mod}'")

    return role_class
