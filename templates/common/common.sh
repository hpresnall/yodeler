# delete unneeded packages
apk -q del $REMOVE_PACKAGES_STR

# basic config
echo "$MOTD" > /etc/motd
setup-timezone -z $TIMEZONE
setup-keymap $KEYMAP
mv /etc/profile.d/color_prompt /etc/profile.d/color_prompt.sh
echo "%wheel ALL=(ALL) ALL" > /etc/sudoers.d/wheel
rootinstall $$DIR/chrony.conf /etc/chrony
sed -i -e "s/umask 022/umask 027/g" /etc/profile

# add basic services
rc-update add networking boot
rc-update add sshd default
rc-update add chronyd default
rc-update add acpid default

if [ "$IS_VM" = "False" ]; then
  rc-update add cpufreqd default
fi

# create user and allow sudo
adduser -D $USER
addgroup $USER wheel
echo "$USER:$PASSWORD" | chpasswd

# setup ssh
mkdir /home/$USER/.ssh
chmod 700 /home/$USER/.ssh
chown $USER:$USER /home/$USER/.ssh
echo "$PUBLIC_SSH_KEY" > /home/$USER/.ssh/authorized_keys
chmod 600 /home/$USER/.ssh/authorized_keys
chown $USER:$USER /home/$USER/.ssh/authorized_keys

if [ "$INSTALL_PRIVATE_SSH_KEY" = "True" ]; then
    echo "Host=*
User=$USER
IdentityFile=~/.ssh/$USER" > /home/$USER/.ssh/config

    echo "$PRIVATE_SSH_KEY" > /home/$USER/.ssh/$USER
fi

# remove root password and SSH access
passwd -l root
echo "PermitRootLogin no" >> /etc/ssh/sshd_config
# only allow private key access
echo "PasswordAuthentication no" >> /etc/ssh/sshd_config

# configure network
echo "$HOSTNAME" > /etc/hostname
rootinstall $$DIR/hosts /etc
rootinstall $$DIR/resolv.conf.head /etc
rootinstall $$DIR/interfaces /etc/network
rootinstall $$DIR/dhclient.conf /etc/dhcp

# Busybox's udhcpc does not work with Debian's ifup / ifdown, so remove it
rm /sbin/udhcpc

# link dhclient to a location ifup can find it
ln -s /usr/sbin/dhclient /sbin/dhclient

# colorize ls and ip commands
echo 'export COLORFGBG=";0"' > /etc/profile.d/aliases.sh
echo 'alias la="ls --color -la"' >> /etc/profile.d/aliases.sh
echo 'alias ls="ls --color"' >> /etc/profile.d/aliases.sh
echo 'alias ip="ip -c"' >> /etc/profile.d/aliases.sh
chmod +x /etc/profile.d/aliases.sh

# cleanup TTYs
if [ "$IS_VM" = "True" ]; then
  # all TTYs on VMs; faster boot
  sed -i -E "s/^tty([1-6])/\#tty\1/g" /etc/inittab
  sed -i -e "s/TIMEOUT 30/TIMEOUT 10/g" /boot/extlinux.conf
else
  # keep 2 TTYs on physical
  sed -i -E "s/^tty([3-6])/\#tty\1/g" /etc/inittab
fi
