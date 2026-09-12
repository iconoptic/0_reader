#!/usr/bin/env bash
# Sync rapid_reader/ and ebooks/ to a live Pi for OTA.
#
# Requires pi.env (repo root, gitignored) with PI_SSH=user@host.
# See pi.env.example. This is host-side config, not card-build input —
# do not put it in ssh_salvage/.
#
# Usage:
#   tools/sync_to_pi.sh                 # stage app + ebooks, arm ota/pending
#   tools/sync_to_pi.sh --app-only      # skip ebooks/
#   tools/sync_to_pi.sh --ebooks-only   # books only; arms nothing
#   tools/sync_to_pi.sh --force-apply   # stage, then apply now over SSH
#   tools/sync_to_pi.sh --no-convert    # skip the local txt_to_txt.py pass
#   tools/sync_to_pi.sh --bootstrap     # one-time migration for cards
#                                       # flashed before OTA existed:
#                                       # installs the apply helper and
#                                       # sudoers rule (prompts for the
#                                       # Pi's password), then stages
#                                       # and applies immediately.
#
# Cards built by tools/build_card.sh already ship the helper and the
# sudoers rule, so --bootstrap is not part of the normal workflow.
#
# Before every ebooks/ sync, tools/txt_to_txt.py is run locally over
# ebooks/*.txt (RSVP cleanup, in place — see README.md). It's idempotent
# and backs up each file to <name>.txt.orig the first time it touches
# it, so re-running sync repeatedly is safe. --no-convert skips this if
# you want to push books as-is. The .orig backups themselves are never
# rsynced to the device.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
ENV_FILE="$HERE/pi.env"
SYNC_APP=1
SYNC_EBOOKS=1
FORCE_APPLY=0
BOOTSTRAP=0
CONVERT=1

usage() {
    # Print the header comment block, whatever length it grows to.
    sed -n '2,/^[^#]/p' "$0" | sed -n 's/^# \?//p'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-only) SYNC_EBOOKS=0 ;;
        --ebooks-only) SYNC_APP=0 ;;
        --force-apply) FORCE_APPLY=1 ;;
        --no-convert) CONVERT=0 ;;
        --bootstrap) BOOTSTRAP=1; FORCE_APPLY=1; SYNC_APP=1 ;;
        -h|--help) usage 0 ;;
        *) echo "unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

[[ -f $ENV_FILE ]] || {
    echo "missing $ENV_FILE — create it with PI_SSH=reader@host (gitignored host-side config; see pi.env.example)" >&2
    exit 1
}
# shellcheck disable=SC1090
source "$ENV_FILE"
[[ -n ${PI_SSH:-} ]] || { echo "PI_SSH unset in $ENV_FILE" >&2; exit 1; }

# Non-interactive by default: a hung password prompt in the middle of an
# rsync or a preflight is worse than a clean failure. Bootstrap is the
# one path that deliberately allows a prompt (see bootstrap()).
ssh_pi() { ssh -o BatchMode=yes "$PI_SSH" "$@"; }

OTA_REMOTE=/var/lib/rapid-reader/ota
INCOMING_REMOTE=$OTA_REMOTE/incoming
PENDING_REMOTE=$OTA_REMOTE/pending
FAILED_REMOTE=$OTA_REMOTE/failed
# Sibling of incoming/, not inside it (phase-0-ota-contracts.md §1) — the
# helper verifies incoming/ against this before touching /opt.
MANIFEST_REMOTE=$OTA_REMOTE/manifest
BOOKS_REMOTE=/home/reader/ebooks

HELPER_LOCAL="$HERE/system/rapid-reader-ota-apply"
HELPER_REMOTE=/usr/local/sbin/rapid-reader-ota-apply
SUDOERS_REMOTE=/etc/sudoers.d/010_rapid-reader
SUDOERS_LINE='reader ALL=(root) NOPASSWD: /usr/sbin/poweroff, /usr/sbin/reboot, /usr/local/sbin/rapid-reader-ota-apply'

[[ -f $HELPER_LOCAL ]] || { echo "missing $HELPER_LOCAL" >&2; exit 1; }
HELPER_SUM=$(sha256sum "$HELPER_LOCAL" | cut -d' ' -f1)

log() { printf '+ %s\n' "$*"; }

# ------------------------------------------------------------------ checks

# Can the device apply an OTA right now?
#   0 = yes
#   1 = helper missing, or not byte-identical to the repo's copy
#   2 = helper present and current, but not reachable under NOPASSWD sudo
#   3 = couldn't reach $PI_SSH at all (network/SSH-level failure, not a
#       software problem on the device)
#
# The checksum comparison is not fussiness: an older helper has no
# --check flag and no argument handling at all, so invoking it to probe
# the sudoers rule would make it *apply the staged tree*. Confirming the
# remote copy matches the one in this repo is what makes the --check
# probe below safe to run, and it doubles as the idempotence test for
# --bootstrap (the helper's contents change between phases).
#
# ssh (with BatchMode=yes) exits 255 specifically for a connection-level
# failure — no route, refused, auth failed — as opposed to the remote
# command's own exit status. That distinction matters here because the
# remote command below always "succeeds" (exit 0) whether or not the
# helper file exists, thanks to `2>/dev/null` and cut being the last
# stage of the pipe; only a real connectivity failure makes ssh itself
# exit 255. Without this check, an unreachable device and a stale helper
# produced the exact same rc=1 and the exact same "helper is missing or
# does not match this repo's copy" message — actively misleading when
# the actual problem is that the Pi is off the network.
device_ready() {
    local remote_sum ssh_rc=0
    # `|| ssh_rc=$?` (not a bare trailing command) so a non-zero ssh exit
    # doesn't trip `set -e` before we get to inspect it — the same reason
    # the previous version of this line used `|| true`, just capturing
    # the code instead of discarding it.
    remote_sum=$(ssh_pi "sha256sum '$HELPER_REMOTE' 2>/dev/null | cut -d' ' -f1" 2>/dev/null) || ssh_rc=$?
    [[ $ssh_rc -ne 255 ]] || return 3
    [[ $remote_sum == "$HELPER_SUM" ]] || return 1
    ssh_pi "sudo -n '$HELPER_REMOTE' --check" >/dev/null 2>&1 || return 2
    return 0
}

manual_bootstrap_help() {
    cat >&2 <<EOF

Could not obtain root on the Pi. To install the helper by hand:

  scp $HELPER_LOCAL $PI_SSH:/tmp/
  ssh $PI_SSH
  sudo install -m 755 -o root -g root /tmp/rapid-reader-ota-apply $HELPER_REMOTE
  printf '%s\\n' '$SUDOERS_LINE' | sudo tee /tmp/rr-sudoers >/dev/null
  sudo visudo -cf /tmp/rr-sudoers
  sudo install -m 440 -o root -g root /tmp/rr-sudoers $SUDOERS_REMOTE
  sudo install -d -m 755 -o reader -g reader $INCOMING_REMOTE

Then re-run: tools/sync_to_pi.sh
EOF
}

# ------------------------------------------------------------- bootstrap

unreachable_help() {  # <where>: printed before exiting on device_ready rc=3
    echo "$1: cannot reach $PI_SSH — no response at the network level," >&2
    echo "not a software problem on the device (ssh exited 255)." >&2
    echo "Check the Pi is powered on, connected, and still at this address" >&2
    echo "before re-running this command." >&2
}

bootstrap() {
    local rc=0
    device_ready || rc=$?
    if [[ $rc -eq 0 ]]; then
        log "bootstrap: helper is current and NOPASSWD sudo works — nothing to do"
        return 0
    fi
    if [[ $rc -eq 3 ]]; then
        unreachable_help bootstrap
        exit 1
    fi
    if [[ $rc -eq 1 ]]; then
        log "bootstrap: helper missing or out of date"
    else
        log "bootstrap: helper present but 'sudo -n' denied — reinstalling sudoers rule"
    fi

    # The privileged half runs from a script rather than a chain of
    # `sudo` invocations so the whole install is one password prompt and
    # the sudoers file is validated before it can lock anyone out.
    local payload
    payload=$(mktemp)
    # shellcheck disable=SC2064  # expand $payload now, not at trap time
    trap "rm -f '$payload'" RETURN
    cat > "$payload" <<EOF
#!/bin/bash
set -euo pipefail
install -m 755 -o root -g root /tmp/rapid-reader-ota-apply '$HELPER_REMOTE'
echo "  installed $HELPER_REMOTE"

# Validate before installing: a malformed drop-in can break sudo for
# every user, on a device whose only other access is the card reader.
tmp=\$(mktemp)
trap 'rm -f "\$tmp"' EXIT
printf '%s\n' '$SUDOERS_LINE' > "\$tmp"
if ! visudo -cf "\$tmp"; then
    echo "  refusing to install a malformed $SUDOERS_REMOTE" >&2
    exit 1
fi
install -m 440 -o root -g root "\$tmp" '$SUDOERS_REMOTE'
echo "  installed $SUDOERS_REMOTE"

install -d -m 755 -o reader -g reader '$INCOMING_REMOTE'
rm -f /tmp/rapid-reader-ota-apply
EOF

    # device_ready above already confirmed the device answered once, but
    # a Pi Zero W on wifi can still drop between that check and here —
    # give that case the same clear message instead of a raw scp error.
    if ! scp -q -o BatchMode=yes "$HELPER_LOCAL" "$PI_SSH:/tmp/rapid-reader-ota-apply"; then
        unreachable_help bootstrap
        exit 1
    fi
    if ! scp -q -o BatchMode=yes "$payload" "$PI_SSH:/tmp/rr-bootstrap.sh"; then
        unreachable_help bootstrap
        exit 1
    fi

    # Prefer passwordless sudo where it already works (a card built by
    # build_card.sh, or a re-run after a successful bootstrap). Fall back
    # to an interactive prompt — `reader` has a real password, set by
    # build_card.sh. Only if both fail do we print manual instructions.
    if ssh_pi 'sudo -n true' 2>/dev/null; then
        log "bootstrap: using passwordless sudo"
        ssh_pi 'sudo -n bash /tmp/rr-bootstrap.sh'
    elif [[ -t 0 ]]; then
        log "bootstrap: no passwordless sudo — prompting for the Pi's 'reader' password"
        if ! ssh -t "$PI_SSH" 'sudo bash /tmp/rr-bootstrap.sh'; then
            manual_bootstrap_help
            exit 1
        fi
    else
        echo "bootstrap: needs a terminal to prompt for the Pi's password" >&2
        manual_bootstrap_help
        exit 1
    fi
    ssh_pi 'rm -f /tmp/rr-bootstrap.sh' || true

    rc=0
    device_ready || rc=$?
    if [[ $rc -eq 3 ]]; then
        echo "bootstrap: install commands completed, but the device dropped off" >&2
        echo "the network before the final verification. Re-run this command" >&2
        echo "once it's reachable again to confirm the install actually took." >&2
        exit 1
    fi
    if [[ $rc -ne 0 ]]; then
        echo "bootstrap: install completed but the device still fails preflight" >&2
        manual_bootstrap_help
        exit 1
    fi
    log "bootstrap: done"
}

# ------------------------------------------------------------- preflight

# Required by every path that ends in an apply, host-driven or app-driven.
preflight_device() {
    local rc=0
    device_ready || rc=$?
    [[ $rc -eq 0 ]] && return 0
    if [[ $rc -eq 3 ]]; then
        unreachable_help preflight
        exit 1
    fi
    if [[ $rc -eq 1 ]]; then
        echo "preflight: $HELPER_REMOTE is missing or does not match this repo's copy" >&2
    else
        echo "preflight: 'sudo -n $HELPER_REMOTE' was denied — the sudoers rule is not in effect" >&2
    fi
    echo "Refusing to touch a device that cannot apply an update." >&2
    echo "Run: tools/sync_to_pi.sh --bootstrap" >&2
    exit 1
}

# Required only before arming ota/pending, because only the app on the
# device consumes it. Deliberately NOT required for --force-apply: that
# path installs the app over SSH, so demanding the new app already be
# present would be the same circular gate that made the old --bootstrap
# impossible to satisfy.
preflight_app() {
    if ssh_pi 'python3 -' <<'PY'
import sys
sys.path.insert(0, "/opt/rapid-reader")
import config
# OTA_PENDING alone proves the app can see the trigger; OTA_FAILED proves
# it is new enough to record a failure instead of retrying forever, which
# is what keeps a bad update from looping on every boot.
raise SystemExit(0 if getattr(config, "OTA_PENDING", "").endswith("/ota/pending")
                 and getattr(config, "OTA_FAILED", "").endswith("/ota/failed") else 1)
PY
    then
        return 0
    fi
    echo "preflight: the app at /opt/rapid-reader is too old to handle ota/pending safely" >&2
    echo "Refusing to arm an update it would not apply (or would retry forever)." >&2
    echo "Install the current app first: tools/sync_to_pi.sh --force-apply" >&2
    exit 1
}

# ------------------------------------------------------------------- run

if [[ $BOOTSTRAP -eq 1 ]]; then
    bootstrap
fi

if [[ $SYNC_APP -eq 1 || $FORCE_APPLY -eq 1 ]]; then
    preflight_device
fi

ssh_pi "mkdir -p '$INCOMING_REMOTE' '$BOOKS_REMOTE'"

if [[ $SYNC_APP -eq 1 ]]; then
    log "rsync rapid_reader/ → $PI_SSH:$INCOMING_REMOTE/"
    rsync -az --delete \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude 'splash/' \
        -e ssh \
        "$HERE/rapid_reader/" "$PI_SSH:$INCOMING_REMOTE/"
    # splash/ is excluded here because the repo doesn't have one to send
    # (card build generates it on-device) — this is not what protects the
    # live splash from an apply's --delete; that's the ota-apply helper's
    # own --exclude 'splash/' on the incoming->/opt rsync.

    log "manifest → $PI_SSH:$MANIFEST_REMOTE"
    # Computed from the local source tree with the same excludes as the
    # rsync above, so the helper's `sha256sum -c` catches exactly the
    # thing phase 4 exists for: a transfer that dropped or truncated
    # files on this Pi Zero W's wifi link (F6), independent of whether
    # rsync itself reported success.
    manifest_tmp=$(mktemp)
    ( cd "$HERE/rapid_reader" && find . -type f \
          ! -path './__pycache__/*' ! -name '*.pyc' ! -path './splash/*' \
          -print0 | sort -z | xargs -0 sha256sum ) > "$manifest_tmp"
    scp -q -o BatchMode=yes "$manifest_tmp" "$PI_SSH:$MANIFEST_REMOTE"
    rm -f "$manifest_tmp"
fi

if [[ $SYNC_EBOOKS -eq 1 ]]; then
    if [[ -d $HERE/ebooks ]]; then
        if [[ $CONVERT -eq 1 ]]; then
            log "txt_to_txt.py: RSVP cleanup of ebooks/*.txt (in place)"
            python3 "$HERE/tools/txt_to_txt.py"
        fi
        log "rsync ebooks/ → $PI_SSH:$BOOKS_REMOTE/"
        rsync -az \
            --exclude '*.orig' \
            -e ssh \
            "$HERE/ebooks/" "$PI_SSH:$BOOKS_REMOTE/"
    else
        log "skip ebooks/ (directory missing)"
    fi
fi

# Arming and force-applying are alternatives, not a sequence: --force-apply
# installs the staged tree over SSH right now, so there is nothing left for
# the app's pending trigger to pick up.
if [[ $SYNC_APP -eq 1 && $FORCE_APPLY -eq 0 ]]; then
    preflight_app
    log "arm OTA pending"
    # Clearing `failed` is the host's job (see config.OTA_FAILED): a new
    # staged tree is a new attempt, and the app must not skip it because
    # a previous one failed.
    ssh_pi "rm -f '$FAILED_REMOTE' && date -u +%Y-%m-%dT%H:%M:%SZ > '$PENDING_REMOTE'"
fi

if [[ $FORCE_APPLY -eq 1 ]]; then
    log "apply now (sudo ota-apply)"
    ssh_pi "sudo -n '$HELPER_REMOTE'"
fi

log "done"
