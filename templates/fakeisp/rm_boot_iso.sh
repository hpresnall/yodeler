#!/bin/sh
# removes CDROM ISO file from a VM
# the vm should be stopped before running this script
set -o errexit

vm=$1

if [ -z $vm ]; then
    echo "please specify the name of the vm"
    exit 1
fi

if [ "$$(virsh domstate $vm)" == "running" ]; then
    echo "cannot remove an ISO from VM when $vm is running"
    exit 1
fi

# remove /dev/hdc from the VM
virsh dumpxml $vm > /tmp/$vm.xml
python3 rm_boot_iso.py /tmp/$vm.xml > /tmp/${vm}_updated.xml
virsh define /tmp/${vm}_updated.xml

rm /tmp/$vm.xml
rm /tmp/${vm}_updated.xml
