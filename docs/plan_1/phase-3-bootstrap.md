# Phase 3 — Make bootstrap actually bootstrap

**Status:** done (host-side verified offline; device run still
outstanding — see "Remaining" at the end). **Depends on:** phase 0 (§4),
phase 2. **Fixes:** F3 (high), F5 (medium).

## Context you need

- [README.md](README.md) findings F3 and F5.
- `tools/sync_to_pi.sh` — whole file, particularly the `--bootstrap`
  block (55-83), the `pending` write (110-113), and `ssh_pi` (46).
- `tools/build_card.sh:168-175` — `reader` has a real password,
  salvaged from `ssh_salvage/password` or defaulting to `reader`.
- `tools/build_card.sh:181-185` — what a *new* card already installs, so
  bootstrap can detect and skip.

## The mistake to not repeat

The current bootstrap gates on `ssh_pi 'sudo -n true'`. On a card built
before the OTA change, sudoers grants NOPASSWD for poweroff and reboot
only, so that probe is denied — always, on exactly the cards that need
bootstrapping. The check is a tautology: it passes only where bootstrap
is unnecessary.

`BatchMode=yes` on every SSH call is what closed off the obvious route.
`reader` has a password; an interactive `sudo` over `ssh -t` prompts for
it and installs the helper in one pass, which is what the fallback text
asks the user to do by hand.

## Deliverables

### 1. Interactive privilege escalation

Rewrite the bootstrap block to use an allocated TTY and interactive
sudo:

```sh
ssh -t "$PI_SSH" 'sudo install -m 755 /tmp/rapid-reader-ota-apply ...'
```

Keep `BatchMode=yes` for the non-interactive paths (rsync, preflight,
the `pending` write) where a hung password prompt would be worse than a
clean failure. Bootstrap is explicitly the interactive path.

Order the attempts: if `sudo -n true` succeeds, use it silently (new
cards, and re-runs after a successful bootstrap); otherwise fall through
to the interactive prompt; only if *that* fails print manual
instructions. Do not lead with the manual instructions.

### 2. Idempotence

`--bootstrap` must be safe to run repeatedly. Check whether the helper
is already installed and current (compare checksums, not mere
existence — the helper changes in phases 1 and 4), and whether the
sudoers line already grants the apply path. Skip what is already done
and say so. A re-run on a fully bootstrapped device should be a no-op
that prints what it verified.

### 3. Validate sudoers before installing it

A malformed `/etc/sudoers.d/010_rapid-reader` can lock the user out of
`sudo` entirely on a device whose only other access is the card reader.
Write to a temp file, run `visudo -cf` against it, and only then
`install` it into place. The current code `tee`s straight to the live
path with no validation.

### 4. Preflight, and do not arm what cannot fire

Implement phase 0 §4. Before `sync_to_pi.sh` writes `pending`, verify
the device can apply: helper present, executable, current; sudoers rule
effective; app on the device new enough to watch for `pending`. On
failure, refuse to write `pending` and tell the user to run
`--bootstrap`.

Today the helper check happens only under `--force-apply` (line 119) —
the one path that does not need it — while the default path arms the
trigger unconditionally. Invert that.

### 5. Honest usage text

`usage()` reprints lines 2-12 of the script. Update those comments so
each flag's description matches what it does after this phase, and drop
the implication that `--bootstrap` is a normal first step rather than a
one-time migration for pre-OTA cards.

## Definition of done

- `bash -n tools/sync_to_pi.sh` passes; `shellcheck` is clean or its
  remaining warnings are individually justified inline.
- On the live pre-OTA Pi: `tools/sync_to_pi.sh --bootstrap` completes
  end to end, prompting once for the `reader` password, with no manual
  `scp`/`ssh`/`sudo` steps.
- Running it a second time reports everything already in place and
  changes nothing.
- `sudo -n /usr/local/sbin/rapid-reader-ota-apply` is permitted
  afterwards, and `sudo -n true` is still *not* (the rule stays scoped
  to the three named commands).
- With the helper deliberately removed, plain `tools/sync_to_pi.sh`
  refuses to write `pending` and names the fix.

## Non-goals

- Provisioning a brand-new card — that is `build_card.sh`, which already
  installs the helper and sudoers rule (`:181-185`).
- Remote reboot, log fetching, or any general-purpose device management.
  This script syncs and arms; that is all.

## Deviation from this brief, as landed

**The app-version preflight does not gate `--force-apply`.**

Phase 0 §4 lists three preflight checks and says all must pass before
arming. Implementing that literally reproduced F3's exact shape: the
third check asks whether the app already on the device understands
`pending`, but `--force-apply` is the path that *installs* that app. On
a pre-OTA card the check can only fail, and it would fail on the one
command capable of fixing it — a gate satisfiable only where it is
unnecessary, which is the tautology this phase exists to remove.

The checks are therefore split by who consumes the result:

| Check | Gates |
|---|---|
| Helper installed and byte-identical to the repo's copy | any apply path (`preflight_device`) |
| `sudo -n <helper> --check` succeeds | any apply path (`preflight_device`) |
| App on device understands `OTA_PENDING`/`OTA_FAILED` | arming `pending` only (`preflight_app`) |

`--force-apply` is host-driven and bypasses the app entirely, so it
needs the first two and not the third. It also no longer writes
`pending` at all: arming a trigger and then immediately applying over
SSH left the app chasing an update that was already installed.

Two further hardenings not in the brief:

- **`device_ready` compares the helper's checksum before probing it.**
  A pre-phase-3 helper has no argument handling whatsoever, so
  `sudo -n <helper> --check` against an old copy would fall straight
  through and *apply the staged tree* — the preflight probe would become
  an unannounced install. Matching the checksum first is what makes the
  probe safe, and it is the same comparison deliverable 2 needs for
  idempotence.
- **The helper rejects unknown arguments with exit 2 before any apply
  work**, so a future flag typo cannot fall through into an install.
  Covered by `test_unknown_argument_refuses_and_does_not_apply`.

## Remaining

Everything in "Definition of done" except the three device items was
verified offline against stubbed `ssh`/`scp`/`rsync` (eleven scenarios:
refusal before staging, arm-vs-force-apply split, bootstrap idempotence,
and both privilege-escalation fallbacks including a real pty). The
generated remote payload was expanded and syntax-checked, and its
sudoers line validated with `visudo -cf`.

Still needs the device:

- `tools/sync_to_pi.sh --bootstrap` end to end against the live pre-OTA
  Pi, prompting once for the `reader` password.
- A second run reporting everything already in place.
- `sudo -n <helper>` permitted afterwards while `sudo -n true` stays
  denied.

Note that `README.md`'s "First-time bootstrap" section still carries the
manual `scp`/`ssh`/`sudo` recipe and is now stale; rewriting it is
[phase 5](phase-5-ux-and-docs.md) deliverable 3, which lands after
phase 4.
