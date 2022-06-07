"""Yodeler - automated, self-contained, simple Alpine VM setup"""
import os
import sys
import logging
import errno

import config.site as site


def yodel():
    """Create all configuration files for the site."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s: %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("usage: yodeler.py <site_path> <output_dir>")
        sys.exit(1)

    site_path = sys.argv[1]
    output_dir = sys.argv[2]

    try:
        os.makedirs(output_dir)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(output_dir):
            pass

    site_cfg = site.load_site(site_path)

    site.write_host_configs(site_cfg, output_dir)


if __name__ == "__main__":
    yodel()
