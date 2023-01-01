echo "Configuring common setup"

# basic config
echo "$MOTD" > /etc/motd
setup-timezone -z $TIMEZONE
setup-keymap $KEYMAP
mv /etc/profile.d/color_prompt.sh.disabled /etc/profile.d/color_prompt.sh
rootinstall $$DIR/chrony.conf /etc/chrony
sed -i -e "s/umask 022/umask 027/g" /etc/profile

# colorize ls and ip commands
echo 'export COLORFGBG=";0"' > /etc/profile.d/aliases.sh
echo 'alias la="ls --color -la"' >> /etc/profile.d/aliases.sh
echo 'alias ls="ls --color"' >> /etc/profile.d/aliases.sh
echo 'alias ip="ip -c"' >> /etc/profile.d/aliases.sh
chmod +x /etc/profile.d/aliases.sh

# cleanup TTYs
if [ "$IS_VM" = "True" ]; then
  # no TTYs on VMs; all access via virsh console
  sed -i -E "s/^tty([1-6])/\#tty\1/g" /etc/inittab

  # only 1s at boot menu; faster boot
  sed -i -e "s/TIMEOUT 30/TIMEOUT 10/g" /boot/extlinux.conf
else
  # keep 2 TTYs on physical
  sed -i -E "s/^tty([3-6])/\#tty\1/g" /etc/inittab

  # force console video mode in kernel opts
  sed -i -e "s/quiet/video=1920x1080 quiet/g" /boot/grub/grub.cfg
fi

if [ "$IS_VM" = "False" ]; then
  # non-root user will be configured by Alpine setup

  # enable cpufreqd on physical systems
  rc-update add cpufreqd default
else
  # create non-root user and allow doas
  adduser -D $USER
  addgroup $USER wheel
  echo "permit persist :wheel" >> /etc/doas.d/doas.conf
fi

# remove root password; only allow access via doas su
passwd -l root
echo "doas su -" > /home/$USER/.ash_history
echo "$USER:$PASSWORD" | chpasswd

# setup SSH
mkdir -p /home/$USER/.ssh
chmod 700 /home/$USER/.ssh
echo "$PUBLIC_SSH_KEY" > /home/$USER/.ssh/authorized_keys
chmod 600 /home/$USER/.ssh/authorized_keys
chown -R $USER:$USER /home/$USER/.ssh

if [ "$INSTALL_PRIVATE_SSH_KEY" = "True" ]; then
    echo "Host=*
User=$USER
IdentityFile=~/.ssh/$SITE" > /home/$USER/.ssh/config

    echo "$PRIVATE_SSH_KEY" > /home/$USER/.ssh/$SITE
    chmod 600 /home/$USER/.ssh/$SITE
fi

# only allow private key access
echo "PermitRootLogin no" >> /etc/ssh/sshd_config
echo "PasswordAuthentication no" >> /etc/ssh/sshd_config

# network confing
echo "$HOSTNAME" > /etc/hostname
rootinstall $$DIR/hosts /etc
rootinstall $$DIR/interfaces /etc/network
rootinstall $$DIR/dhcpcd.conf /etc
if [ -f $$DIR/resolv.conf ]; then
  rootinstall $$DIR/resolv.conf /etc
fi
# prevent dhcpcd starting as a service; let ifupdown-ng start it, if needed
sed -i -e "s/provide net/# provide net/g" /etc/init.d/dhcpcd
# remove dhcpcd messages to stdout
sed -i -e "s#/sbin/dhcpcd \$$optargs#/sbin/dhcpcd -q \$$optargs#g" /usr/libexec/ifupdown-ng/dhcp
