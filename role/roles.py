"""Defines the abstract Role class and helper functions for finding & loading implementations.
A role represents various configurations that can be applied to a host to implement a specific functionality."""
import os
import importlib
import inspect
import logging

from abc import ABC, abstractmethod

import script.shell as shell

_logger = logging.getLogger(__name__)


class Role(ABC):
    """Role is the abstract base class that defines how to configure a specific set of
    functionality on a server.
    """

    def __init__(self, cfg: dict) -> None:
        self.name = self.__class__.__name__.lower()
        self._cfg = cfg

    @abstractmethod
    def additional_packages(self) -> set[str]:
        """The packages needed to implement this role.
        This will be called after configure_interfaces() and additional_configuration()."""

    def additional_aliases(self) -> list[str]:
        """Add any additional aliases for the role.
        Host configuration will ensure unique values for the site will be added to cfg['aliases'] if more than one host
        has this role."""
        return []

    def needs_build_image(self) -> bool:
        """Does this role need to build additional artifacts?
        If so, the site level build image will be mounted for use in write_config()."""
        return False

    def configure_interfaces(self):
        """Add any additional interfaces for the role.
        Interface validation will be run afer all roles have this function called."""
        pass

    def additional_configuration(self):
        """Add any additional default configuration specific to this role.
        This is run after configure_interfaces() and basic host level validation (but before validate()).
        The configuration will be in its final object format for this call."""
        pass

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

        This will called _after_ all hosts for the site are loaded so the total site layout can be checked, if needed."""
        pass

    @abstractmethod
    def write_config(self, setup: shell.ShellScript, output_dir: str):
        """Write any necessary shell script commands to setup.
        Create the configuration files that implement this role.
        """


def load(role_name: str, host_cfg: dict) -> Role:
    """Load a Role subclass instance using the given role name."""
    if host_cfg is None:
        raise ValueError("host_cfg cannot be None")

    role_name = role_name.lower()

    if role_name in _role_class_by_name:
        clazz = _role_class_by_name[role_name]

        # instantiate the class
        try:
            return clazz(host_cfg)
        except TypeError as te:
            raise KeyError(f"cannot instantiate class '{clazz}'") from te
    else:
        raise KeyError(f"cannot find class for role '{role_name}'")


_role_class_by_name = {}

def names() -> list[str]:
    return sorted(_role_class_by_name.keys())


def class_for_name(name: str) -> Role:
    return _role_class_by_name[name]


def load_all():
    """Load all Role subclasses in the 'roles' package.
    This must be called before loading any host configuration."""
    roles_dir = os.path.dirname(__file__)
    ignored_files = ["__init__.py", os.path.basename(__file__)]

    for file in os.listdir(roles_dir):
        if (file[-3:] != '.py') or (file in ignored_files):
            continue

        module_name = os.path.basename(roles_dir) + "." + file[:-3]

        try:
            mod = importlib.import_module(module_name)
        except ModuleNotFoundError as mnfe:
            raise KeyError(f"cannot load module '{module_name}' from '{file}'") from mnfe

        for clazz in inspect.getmembers(mod, inspect.isclass):
            if clazz[0] != 'Role':
                role_name = clazz[0].lower()
                _logger.debug("loaded role '%s' from '%s'", role_name, file)
                _role_class_by_name[role_name] = clazz[1]
