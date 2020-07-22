"""This package contains code run by yodeler/setup.py to configure a host.

Each module defines single role defined in the  host's configuration.
The role name maps to the module name.

Each module _must_ define the following:
1. An iterable 'packages' that contains all packages needed for this role
2. A setup method that takes a host configuration and an output directory.
"""
