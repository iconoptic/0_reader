#!/bin/bash
# Rapid Reader first-boot setup. Local setup (permissions, hardware groups,
# app start) must not depend on network, so the app still runs without wifi;
# only the one-time apt install genuinely needs it and retries next boot.
set -x
export DEBIAN_FRONTEND=noninteractive

WIFI_COUNTRY=US

mkdir -p /var/lib/rapid-reader

rfkill unblock wifi || true
raspi-config nonint do_wifi_country "$WIFI_COUNTRY" || true

mkdir -p /home/reader/ebooks
chown -R 1000:1000 /home/reader/ebooks || true

# app runs as 'reader': hardware access + writable state dir
usermod -aG spi,gpio reader || true
chown -R reader:reader /var/lib/rapid-reader

# lock down: drop blanket passwordless sudo; allow only poweroff/reboot
printf 'reader ALL=(root) NOPASSWD: /usr/sbin/poweroff, /usr/sbin/reboot\n' \
    > /etc/sudoers.d/010_rapid-reader
chmod 440 /etc/sudoers.d/010_rapid-reader
rm -f /etc/sudoers.d/010_pi-nopasswd

systemctl enable rapid-reader.service
systemctl start --no-block rapid-reader.service

# persist logs across power cycles (default is volatile) so a failed boot
# can be diagnosed later via `journalctl --directory` on the mounted card
mkdir -p /var/log/journal
chown root:systemd-journal /var/log/journal
chmod 2755 /var/log/journal
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\n' > /etc/systemd/journald.conf.d/10-persistent.conf
systemctl restart systemd-journald || true

# Wait for the network to come up (apt update doubles as the connectivity test)
ok=""
for i in $(seq 1 40); do
    if apt-get update; then ok=1; break; fi
    sleep 10
done
if [ -z "$ok" ]; then
    echo "network never came up; will retry package install next boot" >&2
    exit 1
fi

apt-get install -y python3-pil python3-spidev python3-gpiozero python3-lgpio \
    fonts-dejavu-core

touch /var/lib/rapid-reader/.setup-done
systemctl disable rapid-reader-setup.service || true
exit 0
