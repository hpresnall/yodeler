import os
import sys
import logging
import errno

import yodeler.setup as setup
import util.file as util


def main():
    logging.basicConfig(level=logging.INFO)

    host_cfgs = setup.load_all_configs("sites", "basic")

    config_dir = "C:/Landing/yodeler"
    try:
        os.makedirs(config_dir)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(config_dir):
            pass

    for host_cfg in host_cfgs.values():
        # print(util.output_yaml(host_cfg))
        setup.create_scripts_for_host(host_cfg, config_dir)
        preview_dir(host_cfg["config_dir"])


def preview_dir(dir, limit=sys.maxsize):
    print(dir)
    print()
    for file in os.listdir(dir):
        path = os.path.join(dir, file)

        if not os.path.isfile(path):
            preview_dir(path, limit)
            continue

        print("**********")
        print(path)
        print()
        n = 0
        with open(path) as f:
            for line in f:
                if n > limit:
                    break
                n += 1
                print(line, end='')
        print()


if __name__ == "__main__":
    main()
