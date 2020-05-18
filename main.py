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

    # vmhost needs a combined set of all packages
    # start with packages required by alpine-make-vm-image script
    all_packages = {"alpine-base", "qemu-img", "mkinitfs", "syslinux", "linux-virt", "linux-lts"}
    # add packages apk fetch -R does not pick up
    all_packages |= {"lua5.2-alt-getopt", "ip6tables-openrc", "cpufreqd-openrc", "dbus-openrc", "lvm2-openrc", "libtirpc-conf", "krb5-conf", "ndisc6-openrc", "openvswitch-openrc", "prometheus-node-exporter-openrc"}
    vmhost = None

    for host_cfg in host_cfgs.values():
        # print(util.output_yaml(host_cfg))
        setup.create_scripts_for_host(host_cfg, config_dir)
        preview_dir(host_cfg["config_dir"])

        # add packages after creating scripts since roles can add packages
        all_packages |= host_cfg["packages"]

        if "vmhost" in host_cfg["roles"]:
            vmhost = host_cfg["hostname"]
            print("vmhost!", vmhost)

    if vmhost is not None:
        util.write(vmhost + "/all_packages", " ".join(all_packages), config_dir)


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
