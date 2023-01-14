"""Defines the abstract Role class.
A role represents various configurations that can be applied to a host to implement a specific functionality."""
import importlib
import inspect

from abc import ABC, abstractmethod

import util.shell as shell;

class Role(ABC):
    """Role is the abstract base class that defines how to configure a specific set of
    functionality on a server.
    """

    def __init__(self, name: str, cfg: dict):
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

    @abstractmethod
    def write_config(self, setup: shell.ShellScript, output_dir: str):
        """Write any necessary shell script commands to setup.
        Create the configuration files that implement this role.
        """


# cache loaded Role subclasses
_role_class_by_name = {}


def load(role_name: str, host_cfg: dict) -> Role:
    """Load an Role subclass instance using the given role name."""
    clazz = _role_class_by_name.setdefault(role_name, _load_role_class(role_name))

    # instantiate the class
    try:
        return clazz(host_cfg)
    except TypeError:
        raise KeyError(f"cannot instantiate class '{clazz}'")


def _load_role_class(role_name: str):
    try:
        mod = importlib.import_module("roles." + role_name)
    except ModuleNotFoundError:
        raise KeyError(f"cannot load module for role '{role_name}' from the roles package")

    # find class for role; assume only 1 class in each module
    role_class = None
    for clazz in inspect.getmembers(mod, inspect.isclass):
        if clazz[0].lower() == role_name.lower():
            role_class = clazz[1]
            break

    if role_class is None:
        raise KeyError(f"cannot find class for role '{role_name}' in module '{mod}'")

    return role_class
    # instantiate the class and add to the list
