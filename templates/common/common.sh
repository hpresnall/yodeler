# basic config
echo "$MOTD" > /etc/motd
setup-timezone -z $TIMEZONE
setup-keymap $KEYMAP
mv /etc/profile.d/color_prompt.sh.disabled /etc/profile.d/color_prompt.sh
rootinstall $$DIR/chrony.conf /etc/chrony
sed -i -e "s/umask 022/umask 027/g" /etc/profile
rc-update add chronyd default
rc-update add acpid boot

# colorize ls and ip commands
echo 'export COLORFGBG=";0"' > /etc/profile.d/aliases.sh
echo 'alias la="ls --color -la"' >> /etc/profile.d/aliases.sh
echo 'alias ls="ls --color"' >> /etc/profile.d/aliases.sh
echo 'alias ip="ip -c"' >> /etc/profile.d/aliases.sh
chmod +x /etc/profile.d/aliases.sh

if [ "$IS_VM" = "True" ]; then
  # no TTYs on VMs; all access via virsh console
  sed -i -E "s/^tty([1-6])/\#tty\1/g" /etc/inittab

  # only 1s at boot menu; faster boot
  sed -i -e "s/TIMEOUT 30/TIMEOUT 10/g" /boot/extlinux.conf

  # create non-root user and allow doas
  adduser -D -g $USER $USER
  addgroup $USER wheel
  echo "permit persist :wheel" >> /etc/doas.d/doas.conf
else
  # keep 2 TTYs on physical
  sed -i -E "s/^tty([3-6])/\#tty\1/g" /etc/inittab

  # force console video mode in kernel opts
  sed -i -e "s/quiet/video=1920x1080 quiet/g" /boot/grub/grub.cfg

  # non-root user will be configured by Alpine setup

  # enable services on physical systems
  rc-update add cpufreqd boot
  rc-update add cgroups sysinit
  # acpid should only be run at boot runlevel
  rc-update del acpid default
fi

# remove root password; only allow access via doas su -
passwd -l root
echo "doas su -" > /home/$USER/.ash_history
chown "$USER:$USER" /home/$USER/.ash_history
echo "$USER:$PASSWORD" | chpasswd

# setup SSH
mkdir -p /home/$USER/.ssh
echo "$PUBLIC_SSH_KEY" > /home/$USER/.ssh/authorized_keys
rc-update add sshd default

if [ "$INSTALL_PRIVATE_SSH_KEY" = "True" ]; then
    echo "Host=*
User=$USER
IdentityFile=~/.ssh/$SITE_NAME" > /home/$USER/.ssh/config

    echo "$PRIVATE_SSH_KEY" > /home/$USER/.ssh/$SITE_NAME
fi

chmod 600 /home/$USER/.ssh/*
chmod 700 /home/$USER/.ssh
chown -R $USER:$USER /home/$USER/.ssh

# only allow private key access
echo "PermitRootLogin no" >> /etc/ssh/sshd_config
echo "PasswordAuthentication no" >> /etc/ssh/sshd_config

# network config
echo "$HOSTNAME" > /etc/hostname
rootinstall $$DIR/hosts /etc
rootinstall $$DIR/interfaces /etc/network
if [ -f $$DIR/dhcpcd.conf ]; then
  rootinstall $$DIR/dhcpcd.conf /etc
fi
if [ -f $$DIR/resolv.conf ]; then
  rootinstall $$DIR/resolv.conf /etc
fi
if [ -f $$DIR/resolv.conf.head ]; then
  rootinstall $$DIR/resolv.conf.head /etc
  # remove resolv.conf from setup
  rm /etc/resolv.conf
fi
# start dhcpcd service before networking; it will wait for interfaces to come up
sed -i -e "s/provide net/# provide net/g" -e "s/before dns/before networking dns/g" /etc/init.d/dhcpcd
# remove dhcpcd messages to stdout on startup; rebind instead of starting dhcpcd just for this interface
sed -i -e "s#/sbin/dhcpcd \$$optargs#/sbin/dhcpcd -q -n \$$optargs#g" /usr/libexec/ifupdown-ng/dhcp

# reduce crond logging level so info messages are not printed to syslog on every execution
echo "CRON_OPTS=\"$$CRON_OPTS -l 5\"" >> /etc/conf.d/crond
# disable every execution every 15 minutes
sed -i "s:\*/15:#\*/15:g" /etc/crontabs/root
