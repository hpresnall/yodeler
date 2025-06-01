IS_VM=$IS_VM
INSTALL_PRIVATE_SSH_KEY=$INSTALL_PRIVATE_SSH_KEY

# avoid errors starting OpenRC based services
mkdir -p /run/openrc/started
mkdir -p /run/openrc/exclusive

# make it look like the system booted
echo default > /run/openrc/softlevel

# basic config
echo "$MOTD" > /etc/motd
setup-timezone -z $TIMEZONE
setup-keymap $KEYMAP
mv /etc/profile.d/color_prompt.sh.disabled /etc/profile.d/color_prompt.sh
rootinstall $$DIR/chrony.conf /etc/chrony
sed -i -e "s/umask 022/umask 027/g" /etc/profile
rc-update add crond default
rc-update add chronyd default
rc-update add acpid boot

# allow larger syslog files and keep 5 copies
sed -i -e "s/-t/-t -s 1024 -b 5/g" /etc/conf.d/syslog
# route all auth logs to /var/log/auth
echo -e "auth,authpriv.* /var/log/auth\n*.*;auth,authpriv.none /var/log/messages\n" > /etc/syslog.conf

# colorize ls and ip commands
echo 'export COLORFGBG=";0"' > /etc/profile.d/aliases.sh
echo 'alias la="ls --color -la"' >> /etc/profile.d/aliases.sh
echo 'alias ls="ls --color"' >> /etc/profile.d/aliases.sh
echo 'alias ip="ip -c"' >> /etc/profile.d/aliases.sh
chmod +x /etc/profile.d/aliases.sh

if [ "$$IS_VM" = "True" ]; then
  # no TTYs on VMs; all access via virsh console
  sed -i -E "s/^tty([1-6])/\#tty\1/g" /etc/inittab

  # only 1s at boot menu; faster boot
  sed -i -e "s/TIMEOUT 30/TIMEOUT 10/g" /boot/extlinux.conf

  # create non-root user and allow doas
  adduser -D -g $USER $USER
  addgroup $USER wheel
  echo "permit persist :wheel" >> /etc/doas.conf
else
  # keep 2 TTYs on physical
  sed -i -E "s/^tty([3-6])/\#tty\1/g" /etc/inittab

  # force console video mode in kernel opts
  sed -i -e "s/quiet/video=1920x1080 quiet/g" /etc/default/grub

  # non-root user will be configured by Alpine setup

  # enable services on physical systems
  rc-update add cpufrequtils
  rc-update add cgroups sysinit
  rc-update add smartd default
  # acpid should only be run at boot runlevel
  rc-update del acpid default

  # default to 'powersave' CPU frequency govenor
  # this should be ideal for newer Intel CPUs
  echo "START_OPTS=\"--governor powersave\"" >> /etc/conf.d/cpufrequtils
fi

# remove root password; only allow access via 'doas su -'
passwd -l root
echo "doas su -" > /home/$USER/.ash_history
chown "$USER:$USER" /home/$USER/.ash_history
echo "$USER:$PASSWORD" | chpasswd

# setup SSH
mkdir -p /home/$USER/.ssh
echo "$PUBLIC_SSH_KEY" > /home/$USER/.ssh/authorized_keys
rc-update add sshd default

if [ "$$INSTALL_PRIVATE_SSH_KEY" = "True" ]; then
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
fi
# start dhcpcd service before networking; it will wait for interfaces to come up
sed -i -e "s/provide net/# provide net/g" -e "s/before dns/before networking dns/g" /etc/init.d/dhcpcd
# remove dhcpcd messages to stdout on startup; rebind instead of starting dhcpcd just for this interface
sed -i -e "s#/sbin/dhcpcd \$$optargs#/sbin/dhcpcd -q -n \$$optargs#g" /usr/libexec/ifupdown-ng/dhcp

# reduce crond logging level so info messages are not printed to syslog on every execution
echo "CRON_OPTS=\"$$CRON_OPTS -l 5\"" >> /etc/conf.d/crond
# disable execution every 15 minutes
sed -i "s:\*/15:#\*/15:g" /etc/crontabs/root
