#!/bin/sh
# adds a CDROM ISO file to a VM and configures it to boot
# the vm should be stopped before running this script
set -o errexit

# name of VM to mount the ISO into
vm=$1
# the path of the ISO
iso=$2

if [ -z $vm ]; then
    echo "please specify the name of the vm"
    exit 1
fi

if [ "$$(virsh domstate $vm)" == "running" ]; then
    echo "cannot add an ISO to a VM image when $vm is running"
    exit 1
fi

if [ -z $iso ]; then
    echo "please specify the path of the ISO"
    exit 2
fi

# also ensures file exists
iso=$(realpath $iso)

# add ISO as cdrom disk /dev/hdc
virsh attach-disk $vm $iso hdc --config --type cdrom --targetbus sata

# make /dev/hdc the first boot option
virsh dumpxml $vm > /tmp/$vm.xml
python3 add_boot_iso.py /tmp/$vm.xml > /tmp/${vm}_updated.xml
virsh define /tmp/${vm}_updated.xml

rm /tmp/$vm.xml
rm /tmp/${vm}_updated.xml
