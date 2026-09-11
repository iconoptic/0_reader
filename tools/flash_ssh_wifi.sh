#!/bin/bash
# TEMPORARY: minimal SD card flash for boot/network bring-up debugging.
# Flashes the stock Raspberry Pi OS Lite image, grows the rootfs, enables
# SSH, and installs wifi credentials. Does NOT install the app, HAT
# overlays, packages, or rename the user -- stock firmware config stays.
#
#   sudo tools/flash_ssh_wifi.sh /dev/sdX [SALVAGE_DIR]
#
# SALVAGE_DIR defaults to $REPO/ssh_salvage when present. Honoured files
# (chmod 600; never printed):
#   wifi.env          -- SSID="..."  PSK="..."
#   password          -- one line: login password for user 'pi'
#   home/authorized_keys
#
# Wipes DEV without further confirmation once started.
set -euo pipefail

DEV=${1:?usage: flash_ssh_wifi.sh /dev/sdX [SALVAGE_DIR]}
HERE=$(cd "$(dirname "$0")/.." && pwd)
SALVAGE=${2:-}
if [[ -z $SALVAGE && -d $HERE/ssh_salvage ]]; then
    SALVAGE=$HERE/ssh_salvage
fi
IMG_XZ=$HERE/sdcard_build/raspios_lite_armhf_latest.img.xz
IMG=$HERE/sdcard_build/raspios.img
WIFI_COUNTRY=US
BOOT=/mnt/rr-boot
ROOT=/mnt/rr-root

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root"
[[ -b $DEV ]] || die "$DEV is not a block device"
[[ $DEV =~ ^/dev/(sd[a-z]|mmcblk[0-9]+|nvme[0-9]+n[0-9]+)$ ]] || die "refusing odd device name $DEV"
ROOTDISK=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || true)
[[ -n $ROOTDISK && /dev/$ROOTDISK == "$DEV" ]] && die "$DEV holds the host root filesystem"
if lsblk -no MOUNTPOINTS "$DEV" | grep -q .; then
    die "$DEV has mounted partitions; unmount them first"
fi
for t in sfdisk partprobe e2fsck resize2fs xz openssl; do
    command -v "$t" >/dev/null || die "missing tool: $t"
done
if [[ -n $SALVAGE ]]; then [[ -d $SALVAGE ]] || die "salvage dir $SALVAGE not found"; fi

part() {
    if [[ $DEV =~ [0-9]$ ]]; then echo "${DEV}p$1"; else echo "${DEV}$1"; fi
}
BOOTP=$(part 1); ROOTP=$(part 2)

cleanup() {
    set +e
    for m in "$BOOT" "$ROOT"; do
        mountpoint -q "$m" && umount -l "$m"
    done
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

# ---------------------------------------------------------------- ssh
log "enabling ssh"
# boot-partition flag (honoured on first boot by Raspberry Pi OS)
: > "$BOOT/ssh"
# also enable the unit directly so ssh is up even if first-boot hooks change
mkdir -p "$ROOT/etc/systemd/system/multi-user.target.wants"
ln -sf /usr/lib/systemd/system/ssh.service \
    "$ROOT/etc/systemd/system/multi-user.target.wants/ssh.service"
# headless: don't block on the first-boot userconfig wizard
ln -sf /dev/null "$ROOT/etc/systemd/system/userconfig.service"

# ---------------------------------------------------------------- user / password / keys
log "user account (pi)"
PASS=raspberry
if [[ -n $SALVAGE && -s $SALVAGE/password ]]; then
    PASS=$(head -n1 "$SALVAGE/password")
    echo "pi password set from $SALVAGE/password"
else
    echo "no salvage password; 'pi' password set to 'raspberry' -- change after login" >&2
fi
HASH=$(openssl passwd -6 -- "$PASS")
# unlock / set password for the stock placeholder user
if grep -q '^pi:' "$ROOT/etc/shadow"; then
    sed -i -E "s|^pi:[^:]*:|pi:${HASH}:|" "$ROOT/etc/shadow"
else
    die "stock image has no 'pi' user in /etc/shadow"
fi
# ensure the account is not expired/locked in passwd
sed -i -E 's|^pi:x:|pi:x:|' "$ROOT/etc/passwd" || true

install -d -m 700 -o 1000 -g 1000 "$ROOT/home/pi/.ssh"
if [[ -n $SALVAGE && -f $SALVAGE/home/authorized_keys ]]; then
    install -m 600 -o 1000 -g 1000 "$SALVAGE/home/authorized_keys" \
        "$ROOT/home/pi/.ssh/authorized_keys"
    echo "authorized_keys installed"
fi

# ---------------------------------------------------------------- wifi
log "wifi"
WIFI_OK=0
if [[ -n $SALVAGE && -d $SALVAGE/nm ]] && compgen -G "$SALVAGE/nm/*" >/dev/null; then
    install -d -m 755 "$ROOT/etc/NetworkManager/system-connections"
    install -m 600 -o 0 -g 0 "$SALVAGE"/nm/* "$ROOT/etc/NetworkManager/system-connections/"
    echo "NetworkManager profiles copied from salvage"
    WIFI_OK=1
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
    WIFI_OK=1
fi
[[ $WIFI_OK -eq 1 ]] || echo "warning: no wifi.env / nm profiles -- card will boot without wifi" >&2

# soft-unblock wifi; country code for regulatory domain
install -d -m 755 "$ROOT/var/lib/systemd/rfkill"
for dev in platform-20300000.mmcnr:wlan platform-3f300000.mmcnr:wlan; do
    echo 0 > "$ROOT/var/lib/systemd/rfkill/$dev"
done
if [[ -n $SALVAGE && -d $SALVAGE/rfkill ]]; then
    cp -a "$SALVAGE"/rfkill/. "$ROOT/var/lib/systemd/rfkill/"
fi
if [[ -f $ROOT/etc/wpa_supplicant/wpa_supplicant.conf ]] && ! grep -q '^country=' "$ROOT/etc/wpa_supplicant/wpa_supplicant.conf"; then
    echo "country=$WIFI_COUNTRY" >> "$ROOT/etc/wpa_supplicant/wpa_supplicant.conf"
fi
# also stamp regdomain on cmdline if not already present (harmless duplicate avoided)
CMD=$BOOT/cmdline.txt
if [[ -f $CMD ]] && ! grep -q 'cfg80211.ieee80211_regdom=' "$CMD"; then
    c=$(tr -d '\n' < "$CMD")
    printf '%s cfg80211.ieee80211_regdom=%s\n' "$c" "$WIFI_COUNTRY" > "$CMD"
fi

log "finishing"
sync
cleanup
trap - EXIT
sync
echo "done -- stock image + ssh + wifi. User: pi  Host: look for the Pi on the LAN / mDNS."
echo "Insert into the Pi and power on."
