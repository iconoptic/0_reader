#!/bin/bash
# Copy the reusable bits off an existing Rapid Reader card before it is
# wiped: WiFi profiles, the `reader` account (password hash + ssh keys) and
# any books the user added. Nothing is printed; everything lands in OUTDIR
# with root-only permissions.
#
#   sudo tools/salvage_card.sh /dev/sdX OUTDIR
set -euo pipefail

DEV=${1:?usage: salvage_card.sh /dev/sdX OUTDIR}
OUT=${2:?usage: salvage_card.sh /dev/sdX OUTDIR}
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ -b $DEV ]] || { echo "$DEV is not a block device" >&2; exit 1; }

ROOTPART=${DEV}2
[[ -b $ROOTPART ]] || ROOTPART=${DEV}p2
if findmnt -rn -S "$ROOTPART" >/dev/null; then
    echo "$ROOTPART is mounted; unmount it first" >&2; exit 1
fi

MNT=$(mktemp -d /tmp/salvage.XXXXXX)
cleanup() { umount "$MNT" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true; }
trap cleanup EXIT
mount -o ro "$ROOTPART" "$MNT"

umask 077
mkdir -p "$OUT"/{nm,etc,home}
chmod 700 "$OUT"

# WiFi (NetworkManager) profiles
if compgen -G "$MNT/etc/NetworkManager/system-connections/*" >/dev/null; then
    cp -a "$MNT"/etc/NetworkManager/system-connections/* "$OUT/nm/"
fi

# reader account: only its own lines from the account databases
for f in passwd shadow group gshadow; do
    [[ -f $MNT/etc/$f ]] && grep -E '^reader:' "$MNT/etc/$f" > "$OUT/etc/$f" || true
done
# groups reader belongs to (for reference when recreating the account)
grep -E '(^|,)reader(,|$)' "$MNT/etc/group" | cut -d: -f1 > "$OUT/etc/reader-groups" || true

# ssh authorized keys, user-added books, saved reading state
[[ -f $MNT/home/reader/.ssh/authorized_keys ]] && \
    cp -a "$MNT/home/reader/.ssh/authorized_keys" "$OUT/home/authorized_keys"
if [[ -d $MNT/home/reader/ebooks ]]; then
    mkdir -p "$OUT/home/ebooks"
    cp -a "$MNT"/home/reader/ebooks/. "$OUT/home/ebooks/"
fi
[[ -f $MNT/var/lib/rapid-reader/state.json ]] && \
    cp -a "$MNT/var/lib/rapid-reader/state.json" "$OUT/state.json"
[[ -f $MNT/etc/hostname ]] && cp "$MNT/etc/hostname" "$OUT/etc/hostname"

# radio state (wifi unblocked + regulatory country) so wifi works on first boot
if [[ -d $MNT/var/lib/systemd/rfkill ]]; then
    mkdir -p "$OUT/rfkill"
    cp -a "$MNT"/var/lib/systemd/rfkill/. "$OUT/rfkill/"
fi
[[ -f $MNT/etc/wpa_supplicant/wpa_supplicant.conf ]] && \
    grep -E '^country=' "$MNT/etc/wpa_supplicant/wpa_supplicant.conf" > "$OUT/etc/wifi-country" || true

echo "salvaged to $OUT:"
find "$OUT" -type f | sed "s|^$OUT/|  |" | sed -E 's|(nm/).*|\1<wifi profile>|' | sort -u
