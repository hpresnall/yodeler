"""Module for the Role base class."""
import typing
from abc import ABC, abstractmethod


class Role(ABC):
    """Role is the abstract base class that defines how to configure a specific set of
    functionality on a server.
    """

    def __init__(self, name):
        self.name = name

    @abstractmethod
    def additional_packages(self) -> typing.Set[str]:
        """The packages needed to implement this role."""

    @abstractmethod
    def additional_ifaces(self, cfg) -> typing.List[dict]:
        """Additional interface definitions this role defines.
        These are interfaces as they would defined in YAML config files. util.interfaces.validate()
        will be called on these interfaces."""

    @abstractmethod
    def create_scripts(self, cfg, output_dir) -> typing.List[str]:
        """Create the shell scripts and other configuration files that implement this role.
        Returns a list of the names of the scripts that need to be run to configure this role."""
