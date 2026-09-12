# Phase 1 — Recovery: make a failed OTA survivable

**Status:** done. **Depends on:** phase 0 (sections 1, 2, 3).
**Fixes:** F1 (critical), F2 (high).

**What landed:** `config.OTA_FAILED`; `App._check_ota` refuses to
re-enter while it exists; `OtaScreen` now distinguishes `_concluded`
(tick has nothing left to do) from `_failed` (genuinely failed —
dismissible via K1 tap, rejoins idle dim/off); `pending` is cleared by
the app immediately before invoking the helper, not by the helper on
success; the helper excludes `splash/` from its rsync and refuses
(non-zero exit, no restart) if `splash/splash.bin` isn't exactly 1024
bytes afterward. Verified against a real missing-helper subprocess call
(no mocks) — see the manual check recorded in the phase 1 work.
Progress reporting is still the placeholder animation; that's phase 4.

Land this before anything else, and before running `sync_to_pi.sh`
against the device again. Everything here is about what happens when an
update goes wrong; none of it makes updates work better, and that is the
point.

## Context you need

- [README.md](README.md) findings F1 and F2, in full.
- `rapid_reader/main.py` — `App._check_ota`, `App.run`'s OTA branch.
- `rapid_reader/screens.py` — `OtaScreen`.
- `system/rapid-reader-ota-apply`.
- `tools/build_card.sh:276-303` — the splash invariant being protected.
- `tests/test_app.py` — `test_ota_pending_wakes_and_applies` and
  `test_ota_ignored_when_already_on_ota_screen` are the existing
  happy-path tests; extend rather than replace them.

## Deliverables

### 1. Clear `pending` so failure cannot loop

Implement phase 0 §1's decision. Whichever owner was chosen, the
invariant to establish is: **after one failed apply attempt, a reboot
does not re-enter `OtaScreen`.** The current code leaves `pending` in
place on every failure path, so the device re-enters on every boot
forever.

Cover the abrupt paths too, not just the clean one: the helper being
absent (`sudo -n` returns non-zero immediately — this is the device's
current state), the helper being killed mid-rsync, and power loss
between arming and applying.

### 2. Give the failed screen an exit

Implement phase 0 §2. `OtaScreen.handle` is currently `pass`
unconditionally; it must distinguish in-progress (keep swallowing input)
from failed (accept the designated dismiss input). On dismissal, leave
the OTA screen and land on a usable stack — reuse `App.pop_to_root`,
which phase 2A already hardened to guarantee a `LibraryScreen` root.

Also route the failed state back into normal idle handling: the OTA
branch in `App.run` currently `continue`s before `_tick_idle()`, so a
failed screen never dims or sleeps and will burn the panel indefinitely.
Keep that bypass for in-progress, drop it for failed.

Surface enough to act on. "Update failed" alone gives the user nothing;
include the helper's exit status or a short reason, since the likely
causes (helper missing, sudoers not updated, disk full) each imply a
different fix.

### 3. Stop the helper from deleting the splash

Add `--exclude 'splash/'` to the `rsync` in
`system/rapid-reader-ota-apply`, mirroring `build_card.sh:276`. Then
enforce phase 0 §3's invariants: verify `splash/splash.bin` is present
and 1024 bytes *after* the copy, and treat a violation as a failed
apply rather than restarting into a device with no splash.

Fix the misplaced comment at `tools/sync_to_pi.sh:95` while you are
here — it claims to keep the device splash on an rsync that was never
the one at risk.

Note for testing: the device's `splash/` may already be gone if any
apply has run. Check before assuming, and if it is missing, note that
only a card rebuild restores it.

### 4. Tests for the paths that brick

The existing OTA tests monkeypatch a *successful* apply. Add, at
minimum:

- helper missing / non-zero exit → `pending` is cleared, screen reports
  failure, and a subsequent `_check_ota` does **not** re-enter
  `OtaScreen`,
- failed screen accepts the dismiss input and lands on `LibraryScreen`,
- failed screen is subject to idle dim/off; in-progress is not,
- helper run against a fixture tree preserves `splash/` and fails when
  `splash.bin` is the wrong size.

The third and fourth need the helper exercised as a script. A bats-style
test or a `tests/` shell fixture invoking it with `INCOMING`/`DEST`
overridden by environment is fine; parameterising those three paths in
the helper is an acceptable change if it keeps the defaults intact.

## Definition of done

- `python -m pytest -q` passes, with the new tests failing against the
  current implementation before the fix and passing after.
- `bash -n system/rapid-reader-ota-apply` and
  `bash -n tools/sync_to_pi.sh` pass.
- Manually verified on the device: arm `pending` with the helper
  deliberately absent, confirm the app shows a failure with a reason,
  confirm the dismiss input returns to the library, confirm a reboot
  comes up normally into the library rather than the OTA screen.
- `/opt/rapid-reader/splash/splash.bin` still present and 1024 bytes
  after an apply.

## Non-goals

- Atomicity, rollback, or real progress reporting — phase 4.
- Making `--bootstrap` work — phase 3. This phase must be landable on a
  device whose helper is installed by hand.
