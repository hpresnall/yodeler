rc-update add named default

rootinstall $DIR/named.conf /etc/bind/
rootinstall -t /var/bind $DIR/zones/*