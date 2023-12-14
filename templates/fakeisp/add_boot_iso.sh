#!/bin/sh
# adds a CDROM iso file to a vm and configures it to boot
# the vm should be stopped
set -o errexit

vm=$1
# this should be the _full_ path to the iso so libvirt can find it
iso=$2 

if [ -z $vm ]; then
    echo "please specify the name of the vm"
    exit 1
fi
if [ -z $iso ]; then
    echo "please specify the full path of the iso"
    exit 1
fi

virsh attach-disk $vm $iso hdc --config --type cdrom --targetbus sata

virsh dumpxml $vm > /tmp/$vm.xml
python3 add_boot_iso.py /tmp/$vm.xml > /tmp/${vm}_updated.xml
virsh define /tmp/${vm}_updated.xml

rm /tmp/$vm.xml
rm /tmp/${vm}_updated.xml
