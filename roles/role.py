"""Defines the abstract Role class. A role represents various configurations that can be applied to a host."""
import typing
import importlib
import inspect

from abc import ABC, abstractmethod


class Role(ABC):
    """Role is the abstract base class that defines how to configure a specific set of
    functionality on a server.
    """

    def __init__(self, name):
        self.name = name

    def additional_configuration(self, cfg):
        """Add any additional default configuration for the role."""

    @abstractmethod
    def additional_packages(self, cfg) -> typing.Set[str]:
        """The packages needed to implement this role."""

    @abstractmethod
    def create_scripts(self, cfg, output_dir) -> typing.List[str]:
        """Create the shell scripts and other configuration files that implement this role.
        Returns a list of the names of the scripts that need to be run to configure this role."""


def load(role_name):
    """Load an Role subclass instance using the given role name."""
    try:
        mod = importlib.import_module("roles." + role_name)
    except ModuleNotFoundError:
        raise KeyError(f"cannot load module for role '{role_name}' from the roles package")

    # find class for role; assume only 1 class in each module
    role_class = None
    for clazz in inspect.getmembers(mod, inspect.isclass):
        if clazz[0].upper() == role_name.upper():
            role_class = clazz[1]
            break

    if role_class is None:
        raise KeyError(f"cannot find class for role '{role_name}' in module {mod}")

    # instantiate the class and add to the list
    try:
        return role_class()
    except TypeError:
        raise KeyError(f"cannot instantiate class '{role_class}'")
