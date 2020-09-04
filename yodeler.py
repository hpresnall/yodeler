"""Yodeler - automated, self-contained, simple Alpine VM setup"""
import os
import sys
import logging
import errno

import yodeler.setup as setup


def yodeler():
    """Create all configuration files for the site."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s: %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("usage: yodeler.py <site_name> <output_dir>")
        sys.exit(1)

    site = sys.argv[1]
    config_dir = sys.argv[2]

    try:
        os.makedirs(config_dir)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(config_dir):
            pass

    host_cfgs = setup.load_all_configs("sites", site)

    for host_cfg in host_cfgs.values():
        # print(util.output_yaml(host_cfg))
        setup.create_scripts_for_host(host_cfg, config_dir)
        #preview_dir(host_cfg["config_dir"])


def preview_dir(output_dir, limit=sys.maxsize):
    """Output all files in the given directory, up to the limit number of lines per file."""
    print(output_dir)
    print()
    for file in os.listdir(output_dir):
        path = os.path.join(output_dir, file)

        if not os.path.isfile(path):
            preview_dir(path, limit)
            continue

        print("**********")
        print(path)
        print()
        line_count = 0
        with open(path) as file:
            for line in file:
                if line_count > limit:
                    break
                line_count += 1
                print(line, end='')
        print()


if __name__ == "__main__":
    yodeler()
