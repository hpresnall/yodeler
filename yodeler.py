"""Yodeler - automated, self-contained, simple Alpine VM setup"""
import sys
import logging

import config.site as site

import role.roles as roles


def yodel():
    """Create all configuration files for the site."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s.%(msecs)03d %(levelname)7s %(message)s", datefmt="%H:%M:%S")

    if len(sys.argv) < 2:
        print("usage: yodeler.py <site_path> <output_dir>")
        sys.exit(1)

    roles.load_all()

    site_cfg = site.load(sys.argv[1])
    site.write_host_scripts(site_cfg, sys.argv[2])


if __name__ == "__main__":
    yodel()
