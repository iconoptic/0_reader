#!/bin/bash
# Back up a Rapid Reader card and rebuild it, in one step.
#
# Wraps salvage_card.sh + build_card.sh and adds the guard rails the pair
# does not have on its own: the backup is checked for a readable reading
# state (positions, bookmarks, settings) *before* anything is erased, the
# wipe is confirmed against a listing of the target device, and the rebuilt
# card is mounted read-only afterwards to prove the state came back.
#
#   sudo tools/refresh_card.sh /dev/sdX                   back up + rebuild in place
#   sudo tools/refresh_card.sh --swap /dev/sdX            back up, then rebuild onto
#                                                         a different card
#   sudo tools/refresh_card.sh --backup-only /dev/sdX     back up and stop
#   sudo tools/refresh_card.sh --restore DIR /dev/sdX     rebuild from an old backup
#
# Backups are timestamped directories under /var/backups/rapid-reader
# (root-only, never overwritten); `latest` points at the newest one. They
# hold the reader's password hash and wifi PSKs, so keep them root-only.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
BACKUP_ROOT=/var/backups/rapid-reader
MODE=full
RESTORE_DIR=
SWAP=0
ASSUME_YES=0
FORCE=0
DEV=

log()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die()  { echo "error: $*" >&2; exit 1; }
usage() { sed -n '2,${/^#/!q; s/^# \{0,1\}//; p}' "$0"; }

while [[ $# -gt 0 ]]; do
    case $1 in
        --backup-only) MODE=backup ;;
        --restore)     MODE=restore; RESTORE_DIR=${2:?--restore needs a backup directory}; shift ;;
        --backup-dir)  BACKUP_ROOT=${2:?--backup-dir needs a path}; shift ;;
        --swap)        SWAP=1 ;;
        -y|--yes)      ASSUME_YES=1 ;;
        --force)       FORCE=1 ;;
        -h|--help)     usage; exit 0 ;;
        -*)            die "unknown option $1 (try --help)" ;;
        *)             [[ -z $DEV ]] || die "unexpected argument $1"; DEV=$1 ;;
    esac
    shift
done

[[ $EUID -eq 0 ]] || die "run as root"
[[ -n $DEV ]] || { usage >&2; exit 1; }
[[ -b $DEV ]] || die "$DEV is not a block device"
[[ $DEV =~ ^/dev/(sd[a-z]|mmcblk[0-9]+|nvme[0-9]+n[0-9]+)$ ]] || die "refusing odd device name $DEV"
ROOTDISK=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || true)
[[ -n $ROOTDISK && /dev/$ROOTDISK == "$DEV" ]] && die "$DEV holds the host root filesystem"

# fail before touching anything if the rebuild could not run anyway
if [[ $MODE != backup ]]; then
    [[ -x $HERE/tools/build_card.sh ]] || die "missing $HERE/tools/build_card.sh"
    [[ -f $HERE/sdcard_build/raspios_lite_armhf_latest.img.xz || -f $HERE/sdcard_build/raspios.img ]] \
        || die "missing sdcard_build/raspios_lite_armhf_latest.img.xz -- build_card.sh needs it"
fi
[[ $MODE == restore ]] || [[ -x $HERE/tools/salvage_card.sh ]] || die "missing $HERE/tools/salvage_card.sh"

MNT=
cleanup() {
    [[ -n $MNT ]] || return 0
    umount "$MNT" 2>/dev/null || true
    rmdir "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

rootpart() { # rootpart DEVICE -> partition 2 node
    local p=${1}2
    [[ -b $p ]] || p=${1}p2
    echo "$p"
}

count_files() { # count_files DIR -> plain files directly in DIR, 0 if it does not exist
    local n
    n=$(find "$1" -maxdepth 1 -type f 2>/dev/null | wc -l) || n=0
    echo "$n"
}

count_books() { # count_books DIR -> .txt/.epub anywhere under DIR (library tree)
    local n
    n=$(find "$1" -type f \( -name '*.txt' -o -name '*.epub' \) 2>/dev/null | wc -l) || n=0
    echo "$n"
}

# ---------------------------------------------------------------- verify
summarise_state() { # summarise_state FILE -> one line about the saved reading state
    python3 - "$1" <<'PY'
import json, os, sys
try:
    state = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"UNREADABLE ({exc})"); raise SystemExit(1)
books = state.get("books") or {}
if not books and state.get("positions"):  # v1 file; the app migrates it on load
    books = {p: {"position": v} for p, v in state["positions"].items()}
started = sum(1 for b in books.values() if isinstance(b, dict) and b.get("position"))
marks = sum(len(b.get("bookmarks") or []) for b in books.values() if isinstance(b, dict))
last = os.path.basename(state.get("last_book") or "") or "none"
print(f"{len(books)} book(s) tracked, {started} in progress, {marks} bookmark(s), last read: {last}")
PY
}

verify_backup() { # verify_backup DIR -- refuses to continue if the reading state is gone
    local dir=$1 state_ok=0 line books wifi
    [[ -d $dir ]] || die "backup directory $dir not found"

    if [[ -f $dir/state.json ]] && line=$(summarise_state "$dir/state.json" 2>/dev/null); then
        state_ok=1
        echo "  reading state : $line"
    elif [[ -f $dir/state.json ]]; then
        echo "  reading state : PRESENT BUT UNREADABLE (not valid JSON)"
    else
        echo "  reading state : MISSING"
    fi

    books=$(count_books "$dir/home/ebooks")
    wifi=$(count_files "$dir/nm")
    echo "  added books   : $books"
    echo "  wifi profiles : $wifi$([[ -s $dir/wifi.env ]] && echo " (+ wifi.env)")"
    echo "  ssh key       : $([[ -f $dir/home/authorized_keys ]] && echo yes || echo no)"
    # mirrors build_card.sh: a locked/absent hash falls back to reader/reader
    local pw="none -- the new card gets reader/reader" hash
    if [[ -s $dir/password ]]; then
        pw="from $dir/password"
    elif [[ -s $dir/etc/shadow ]]; then
        hash=$(cut -d: -f2 "$dir/etc/shadow")
        [[ -n $hash && $hash != '!'* && $hash != '*' ]] && pw="carried over from the old card"
    fi
    echo "  password      : $pw"
    if [[ $wifi -eq 0 && ! -s $dir/wifi.env ]]; then
        echo "  note: no wifi settings in this backup; the new card will have no network" >&2
    fi

    if [[ $state_ok -eq 0 && $FORCE -eq 0 ]]; then
        cat >&2 <<EOF

Refusing to erase anything: this backup has no usable reading state, so a
rebuild would lose your ebook progress, bookmarks and settings.
EOF
        if [[ $MODE == restore ]]; then
            echo "Check that $dir is the right backup, or re-run with --force." >&2
        else
            cat >&2 <<EOF

Likely causes: $DEV is not the reader's card, or the reader never saved
state on it. Check the device, or re-run with --force to rebuild anyway.
The backup just taken is kept either way, at:
  $dir
EOF
        fi
        exit 1
    fi
}

verify_card() { # verify_card DIR -- read the rebuilt card back and prove the data landed
    local dir=$1 part
    part=$(rootpart "$DEV")
    [[ -b $part ]] || { echo "cannot re-read $part to verify" >&2; return 0; }
    MNT=$(mktemp -d /tmp/rr-verify.XXXXXX)
    mount -o ro "$part" "$MNT"
    if [[ -f $dir/state.json ]]; then
        if cmp -s "$dir/state.json" "$MNT/var/lib/rapid-reader/state.json"; then
            echo "  reading state : restored ($(summarise_state "$MNT/var/lib/rapid-reader/state.json"))"
        else
            die "state.json on the card does not match the backup -- your progress did NOT restore (backup kept at $dir)"
        fi
    fi
    echo "  books on card : $(count_books "$MNT/home/reader/ebooks")"
    echo "  wifi profiles : $(count_files "$MNT/etc/NetworkManager/system-connections")"
    umount "$MNT"; rmdir "$MNT"; MNT=
}

confirm() { # confirm PROMPT
    [[ $ASSUME_YES -eq 1 ]] && return 0
    [[ -t 0 ]] || die "not running on a terminal; pass --yes to skip confirmation"
    local answer
    read -rp "$1 " answer
    [[ $answer == YES ]] || die "aborted -- nothing was erased"
}

# ---------------------------------------------------------------- backup
BACKUP=$RESTORE_DIR
if [[ $MODE != restore ]]; then
    log "backing up $DEV"
    install -d -m 700 "$BACKUP_ROOT"
    BACKUP=$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)
    mkdir -m 700 "$BACKUP"
    if ! "$HERE/tools/salvage_card.sh" "$DEV" "$BACKUP"; then
        rmdir "$BACKUP" 2>/dev/null || true   # don't leave an empty dir looking like a backup
        die "backup failed -- nothing was erased"
    fi
    ln -sfn "$BACKUP" "$BACKUP_ROOT/latest"
fi

log "checking backup $BACKUP"
verify_backup "$BACKUP"

if [[ $MODE == backup ]]; then
    echo
    echo "backup complete: $BACKUP"
    echo "rebuild a card from it with:"
    echo "  sudo tools/refresh_card.sh --restore $BACKUP /dev/sdX"
    exit 0
fi

# ---------------------------------------------------------------- rebuild
if [[ $SWAP -eq 1 ]]; then
    log "swap the card"
    echo "Backup is safe at $BACKUP."
    [[ -t 0 ]] || die "--swap needs a terminal"
    read -rp "Remove $DEV, insert the new card, then press Enter. " _
    udevadm settle
    [[ -b $DEV ]] || die "no card at $DEV now -- find the new node with lsblk and run:
  sudo tools/refresh_card.sh --restore $BACKUP /dev/sdY"
fi

log "target device"
lsblk -o NAME,SIZE,MODEL,TRAN,MOUNTPOINTS "$DEV"
confirm "ERASE $DEV and rebuild it from $BACKUP? Type YES to continue:"

log "rebuilding $DEV"
"$HERE/tools/build_card.sh" "$DEV" "$BACKUP"

sync; udevadm settle
log "verifying restored data"
verify_card "$BACKUP"

echo
echo "done -- $DEV is ready, rebuilt from $BACKUP"
