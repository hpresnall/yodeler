#!/bin/sh
# removes CDROM iso file from a vm
# the vm should be stopped
set -o errexit

vm=$1

if [ -z $vm ]; then
    echo "please specify the name of the vm"
    exit 1
fi

virsh dumpxml $vm > /tmp/$vm.xml
python3 rm_boot_iso.py /tmp/$vm.xml > /tmp/${vm}_updated.xml
virsh define /tmp/${vm}_updated.xml

rm /tmp/$vm.xml
rm /tmp/${vm}_updated.xml
