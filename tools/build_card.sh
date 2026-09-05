#!/bin/bash
# Build a ready-to-boot Rapid Reader SD card from a stock Raspberry Pi OS
# Lite (armhf, Trixie) image. Everything is done offline on the build host:
# the card is flashed, the root partition grown to fill the card, the
# required Debian packages installed through a qemu-user chroot, the app
# deployed and the systemd unit enabled. First boot goes straight into the
# reader -- no first-boot wizard, no network dependency.
#
#   sudo tools/build_card.sh /dev/sdX [SALVAGE_DIR]
#
# SALVAGE_DIR is the output of tools/salvage_card.sh from a previous card
# (wifi profiles, reader password hash, ssh keys, user-added books). Two
# optional hand-written files are also honoured there (create them as root,
# chmod 600; they are never printed):
#   wifi.env   -- two lines:  SSID="My Network"   PSK="passphrase"
#   password   -- one line: the login password for user 'reader'
#
# Host requirements: xz, sfdisk, partprobe, e2fsck/resize2fs, rsync,
# qemu-arm-static with binfmt_misc registered, python3 + Pillow (for the
# splash images). Wipes DEV without further confirmation once started.
set -euo pipefail

DEV=${1:?usage: build_card.sh /dev/sdX [SALVAGE_DIR]}
SALVAGE=${2:-}
HERE=$(cd "$(dirname "$0")/.." && pwd)
IMG_XZ=$HERE/sdcard_build/raspios_lite_armhf_latest.img.xz
IMG=$HERE/sdcard_build/raspios.img
HOSTNAME_NEW=rapidreader
WIFI_COUNTRY=US
BOOT=/mnt/rr-boot
ROOT=/mnt/rr-root
PKGS="python3-pil python3-spidev python3-lgpio python3-gpiozero fonts-dejavu-core"

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root"
[[ -b $DEV ]] || die "$DEV is not a block device"
[[ $DEV =~ ^/dev/(sd[a-z]|mmcblk[0-9]+|nvme[0-9]+n[0-9]+)$ ]] || die "refusing odd device name $DEV"
# never touch the disk the host is running from
ROOTDISK=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || true)
[[ -n $ROOTDISK && /dev/$ROOTDISK == "$DEV" ]] && die "$DEV holds the host root filesystem"
if lsblk -no MOUNTPOINTS "$DEV" | grep -q .; then
    die "$DEV has mounted partitions; unmount them first"
fi
for t in sfdisk partprobe e2fsck resize2fs rsync qemu-arm-static python3 xz; do
    command -v "$t" >/dev/null || die "missing tool: $t"
done
[[ -e /proc/sys/fs/binfmt_misc/qemu-arm ]] || die "binfmt_misc qemu-arm not registered"
if [[ -n $SALVAGE ]]; then [[ -d $SALVAGE ]] || die "salvage dir $SALVAGE not found"; fi

part() { # part N -> partition node
    if [[ $DEV =~ [0-9]$ ]]; then echo "${DEV}p$1"; else echo "${DEV}$1"; fi
}
BOOTP=$(part 1); ROOTP=$(part 2)

cleanup() {
    set +e
    for m in "$ROOT/boot/firmware" "$ROOT/dev/pts" "$ROOT/dev" "$ROOT/proc" "$ROOT/sys" "$ROOT/run" "$BOOT" "$ROOT"; do
        mountpoint -q "$m" && umount -l "$m"
    done
    rm -f "$ROOT/usr/bin/qemu-arm-static"
}
trap cleanup EXIT

# ---------------------------------------------------------------- image
log "decompressing image"
if [[ ! -f $IMG || $IMG -ot $IMG_XZ ]]; then
    [[ -f $IMG_XZ ]] || die "missing $IMG_XZ"
    xz -dk -T0 -c "$IMG_XZ" > "$IMG"
fi

log "flashing $IMG -> $DEV"
lsblk -o NAME,SIZE,MODEL,TRAN "$DEV"
wipefs -a "$DEV" >/dev/null
dd if="$IMG" of="$DEV" bs=4M conv=fsync status=progress
sync; partprobe "$DEV"; udevadm settle
[[ -b $ROOTP ]] || die "$ROOTP did not appear after flashing"

log "growing root partition to fill the card"
echo ", +" | sfdisk -N 2 --no-reread --force "$DEV" >/dev/null
partprobe "$DEV"; udevadm settle
e2fsck -fy "$ROOTP" >/dev/null || true
resize2fs "$ROOTP"

# ---------------------------------------------------------------- mount
log "mounting"
mkdir -p "$BOOT" "$ROOT"
mount "$ROOTP" "$ROOT"
mount "$BOOTP" "$BOOT"
mkdir -p "$ROOT/boot/firmware"
mount --bind "$BOOT" "$ROOT/boot/firmware"

# ---------------------------------------------------------------- firmware config
log "boot config"
CFG=$BOOT/config.txt
# strip things a headless Zero W with an SPI HAT does not need (faster boot)
sed -i -E 's/^(dtparam=audio=on|camera_auto_detect=1|display_auto_detect=1|dtoverlay=vc4-kms-v3d|max_framebuffers=2|disable_fw_kms_setup=1)$/#\1/' "$CFG"
cat >> "$CFG" <<'EOF'

[all]
# --- Rapid Reader: Waveshare Zero LCD HAT (A) ---
dtparam=spi=on
# 1.3" main screen sits on SPI1 CE0 (GPIO18); the 0.96" sides on SPI0 CE0/CE1
dtoverlay=spi1-1cs
# free the PL011 UART / save boot time; bluetooth is unused
dtoverlay=disable-bt
disable_splash=1
boot_delay=0
EOF

CMD=$BOOT/cmdline.txt
c=$(cat "$CMD")
c=${c//console=serial0,115200 /}
c=${c// resize/}
c="$c quiet loglevel=3 spidev.bufsiz=65536 cfg80211.ieee80211_regdom=$WIFI_COUNTRY"
printf '%s\n' "$c" > "$CMD"
# cloud-init seed files from the stock image: we configure everything statically
rm -f "$BOOT"/user-data "$BOOT"/network-config "$BOOT"/meta-data

# ---------------------------------------------------------------- chroot
log "preparing chroot"
cp /usr/bin/qemu-arm-static "$ROOT/usr/bin/"
mount -t proc proc "$ROOT/proc"
mount -t sysfs sys "$ROOT/sys"
mount --bind /dev "$ROOT/dev"
mount --bind /dev/pts "$ROOT/dev/pts"
mount -t tmpfs tmpfs "$ROOT/run"
mkdir -p "$ROOT/run/systemd/resolve"
cp -L /etc/resolv.conf "$ROOT/run/systemd/resolve/stub-resolv.conf" 2>/dev/null || true
cp -L /etc/resolv.conf "$ROOT/etc/resolv.conf.build"
inchroot() { chroot "$ROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 HOME=/root "$@"; }

# Debian's resolv.conf may be a symlink into /run; make lookups work in the chroot
if [[ -L $ROOT/etc/resolv.conf ]]; then RESOLV_LINK=$(readlink "$ROOT/etc/resolv.conf"); rm "$ROOT/etc/resolv.conf"; fi
cp "$ROOT/etc/resolv.conf.build" "$ROOT/etc/resolv.conf"

log "installing packages: $PKGS"
inchroot apt-get -qq update
inchroot apt-get -qq install -y --no-install-recommends $PKGS
inchroot apt-get -qq clean
rm -rf "$ROOT"/var/lib/apt/lists/*

# restore resolv.conf arrangement
rm -f "$ROOT/etc/resolv.conf" "$ROOT/etc/resolv.conf.build"
[[ -n ${RESOLV_LINK:-} ]] && ln -s "$RESOLV_LINK" "$ROOT/etc/resolv.conf"

# ---------------------------------------------------------------- users
log "user account"
# stock image ships a locked placeholder 'pi' (uid 1000) meant to be renamed
# by the first-boot wizard; do that here.
if inchroot id pi >/dev/null 2>&1; then
    inchroot usermod -l reader -d /home/reader -m pi
    inchroot groupmod -n reader pi
fi
inchroot usermod -aG spi,gpio,video reader
HASH=""
if [[ -n $SALVAGE && -s $SALVAGE/etc/shadow ]]; then
    HASH=$(cut -d: -f2 "$SALVAGE/etc/shadow")
fi
if [[ -n $SALVAGE && -s $SALVAGE/password ]]; then
    printf 'reader:%s\n' "$(head -n1 "$SALVAGE/password")" | inchroot chpasswd
    echo "reader password set from $SALVAGE/password"
elif [[ -n $HASH && $HASH != '!'* && $HASH != '*' ]]; then
    inchroot usermod -p "$HASH" reader
else
    echo "no salvaged password; 'reader' password set to 'reader' -- change it after first login" >&2
    echo 'reader:reader' | inchroot chpasswd
fi
install -d -m 700 -o 1000 -g 1000 "$ROOT/home/reader/.ssh"
if [[ -n $SALVAGE && -f $SALVAGE/home/authorized_keys ]]; then
    install -m 600 -o 1000 -g 1000 "$SALVAGE/home/authorized_keys" "$ROOT/home/reader/.ssh/authorized_keys"
fi
# only poweroff/reboot without a password (used by the app's power-off screen)
printf 'reader ALL=(root) NOPASSWD: /usr/sbin/poweroff, /usr/sbin/reboot\n' > "$ROOT/etc/sudoers.d/010_rapid-reader"
chmod 440 "$ROOT/etc/sudoers.d/010_rapid-reader"

# ---------------------------------------------------------------- system
log "hostname / network / services"
echo "$HOSTNAME_NEW" > "$ROOT/etc/hostname"
sed -i -E "s/^(127\.0\.1\.1\s+).*/\1$HOSTNAME_NEW/" "$ROOT/etc/hosts"
grep -q '^127.0.1.1' "$ROOT/etc/hosts" || echo "127.0.1.1	$HOSTNAME_NEW" >> "$ROOT/etc/hosts"

if [[ -n $SALVAGE && -d $SALVAGE/nm ]] && compgen -G "$SALVAGE/nm/*" >/dev/null; then
    install -d -m 755 "$ROOT/etc/NetworkManager/system-connections"
    install -m 600 -o 0 -g 0 "$SALVAGE"/nm/* "$ROOT/etc/NetworkManager/system-connections/"
fi
if [[ -n $SALVAGE && -s $SALVAGE/wifi.env ]]; then
    SSID=""; PSK=""
    # shellcheck disable=SC1090
    source "$SALVAGE/wifi.env"
    [[ -n $SSID && -n $PSK ]] || die "wifi.env must define SSID and PSK"
    install -d -m 755 "$ROOT/etc/NetworkManager/system-connections"
    NMF="$ROOT/etc/NetworkManager/system-connections/preconfigured.nmconnection"
    (umask 077; cat > "$NMF" <<EOF
[connection]
id=preconfigured
type=wifi
autoconnect=true

[wifi]
mode=infrastructure
ssid=$SSID

[wifi-security]
key-mgmt=wpa-psk
psk=$PSK

[ipv4]
method=auto

[ipv6]
method=auto
addr-gen-mode=default
EOF
    )
    chown 0:0 "$NMF"; chmod 600 "$NMF"
    echo "wifi profile written for SSID (hidden)"
fi
# wifi is soft-blocked on a fresh image until a country is set; unblock it
install -d -m 755 "$ROOT/var/lib/systemd/rfkill"
for dev in platform-20300000.mmcnr:wlan platform-3f300000.mmcnr:wlan; do
    echo 0 > "$ROOT/var/lib/systemd/rfkill/$dev"
done
if [[ -n $SALVAGE && -d $SALVAGE/rfkill ]]; then
    install -d -m 755 "$ROOT/var/lib/systemd/rfkill"
    cp -a "$SALVAGE"/rfkill/. "$ROOT/var/lib/systemd/rfkill/"
fi
if [[ -f $ROOT/etc/wpa_supplicant/wpa_supplicant.conf ]] && ! grep -q '^country=' "$ROOT/etc/wpa_supplicant/wpa_supplicant.conf"; then
    echo "country=$WIFI_COUNTRY" >> "$ROOT/etc/wpa_supplicant/wpa_supplicant.conf"
fi

# persistent journal so a bad boot can be read off the card afterwards
install -d -m 2755 -o 0 -g systemd-journal "$ROOT/var/log/journal" 2>/dev/null || install -d -m 2755 "$ROOT/var/log/journal"
install -d "$ROOT/etc/systemd/journald.conf.d"
printf '[Journal]\nStorage=persistent\nSystemMaxUse=32M\n' > "$ROOT/etc/systemd/journald.conf.d/10-persistent.conf"

# first-boot machinery we have replaced
inchroot systemctl disable userconfig.service sshswitch.service rpi-resize.service 2>/dev/null || true
inchroot systemctl mask userconfig.service 2>/dev/null || true
# unused radios/daemons
inchroot systemctl disable bluetooth.service hciuart.service triggerhappy.service 2>/dev/null || true
inchroot systemctl enable ssh.service
if inchroot dpkg -s cloud-init >/dev/null 2>&1; then touch "$ROOT/etc/cloud/cloud-init.disabled"; fi

# ---------------------------------------------------------------- app
log "deploying application"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude 'splash/' \
    "$HERE/rapid_reader/" "$ROOT/opt/rapid-reader/"
mkdir -p "$ROOT/opt/rapid-reader/splash"
python3 "$HERE/tools/make_splash.py" "$ROOT/opt/rapid-reader/splash"
chown -R 0:0 "$ROOT/opt/rapid-reader"
chmod -R a+rX "$ROOT/opt/rapid-reader"

install -m 644 "$HERE/system/rapid-reader.service" "$ROOT/etc/systemd/system/rapid-reader.service"
inchroot systemctl enable rapid-reader.service

install -d -o 1000 -g 1000 "$ROOT/home/reader/ebooks"
cp -n "$HERE"/ebooks/* "$ROOT/home/reader/ebooks/"
if [[ -n $SALVAGE && -d $SALVAGE/home/ebooks ]]; then
    cp -n "$SALVAGE"/home/ebooks/* "$ROOT/home/reader/ebooks/" 2>/dev/null || true
fi
chown -R 1000:1000 "$ROOT/home/reader"

install -d -m 755 -o 1000 -g 1000 "$ROOT/var/lib/rapid-reader"
if [[ -n $SALVAGE && -f $SALVAGE/state.json ]]; then
    install -m 644 -o 1000 -g 1000 "$SALVAGE/state.json" "$ROOT/var/lib/rapid-reader/state.json"
fi

# ---------------------------------------------------------------- verify
log "verifying"
diff -r -x '__pycache__' -x '*.pyc' -x splash "$HERE/rapid_reader" "$ROOT/opt/rapid-reader" && echo "app files match repo"
for f in main left right; do [[ -s $ROOT/opt/rapid-reader/splash/$f.rgb565 ]] || die "missing splash $f"; done
[[ -L $ROOT/etc/systemd/system/multi-user.target.wants/rapid-reader.service ]] || die "service not enabled"
# import everything under the target's own python (via qemu) as the reader
# user, from the service's working directory (lgpio drops a FIFO in the cwd)
inchroot su -s /bin/sh reader -c 'cd /var/lib/rapid-reader && timeout 120 python3 - <<"PY"
import sys; sys.path.insert(0, "/opt/rapid-reader")
import PIL, spidev, gpiozero, lgpio
import config, lcd, display, render, rsvp, books, main
img = render.word_frame("verify")
assert img.size == (config.MAIN_W, config.MAIN_H)
assert len(lcd.rgb565(img)) == config.MAIN_W * config.MAIN_H * 2
print("target python", sys.version.split()[0], "PIL", PIL.__version__, "OK")
PY'
rm -f "$ROOT"/var/lib/rapid-reader/.lgd-nfy*
grep -E '^(dtparam=spi=on|dtoverlay=spi1-1cs)$' "$CFG" >/dev/null || die "config.txt missing SPI settings"
grep -q 'spidev.bufsiz' "$CMD" || die "cmdline not updated"
echo "hostname: $(cat "$ROOT/etc/hostname")  user: $(inchroot id reader)"
echo "wifi profiles: $(ls "$ROOT/etc/NetworkManager/system-connections" 2>/dev/null | wc -l)"
echo "books: $(ls "$ROOT/home/reader/ebooks" | wc -l)"

log "finishing"
rm -f "$ROOT/usr/bin/qemu-arm-static"
sync
cleanup
trap - EXIT
sync
echo "done -- card is ready. Insert into the Pi and power on."
