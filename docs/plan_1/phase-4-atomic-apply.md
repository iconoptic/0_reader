# Phase 4 — Atomic apply and honest progress

**Status:** done (offline/unit-tested; device run still outstanding —
see "Remaining" at the end). **Depends on:** phase 0 (§3, §5), phase 1.
**Fixes:** F6 (medium), F7 (medium).

**What landed:** the helper now stages into `$DEST.new` beside the live
tree, verifies a host-written `manifest` (sha256 per file) against
`incoming/` before touching anything, checks the phase 0 §3 required-file
list on both the staged and assembled trees, carries the live `splash/`
forward into `.new`, applies ownership/mode during commit, swaps
`$DEST`→`$DEST.prev`→(new)`$DEST`, and re-verifies splash + ownership
*after* the swap — rolling straight back to `.prev` if that fails,
before the service is ever restarted into a bad tree. It writes
`config.OTA_PROGRESS` as `"<n>/4 <stage>"` at each of verifying /
copying / committing / restarting; `OtaScreen` now spawns it with
`subprocess.Popen` and polls from `tick` instead of blocking the event
loop, maps the progress file straight to a fraction/label (no synthetic
animation), and enforces `config.OTA_TIMEOUT_SECS` (120s) with a
SIGTERM-then-SIGKILL escalation if the helper never returns.
`tools/sync_to_pi.sh` computes the manifest from the local source tree
(same excludes as its app rsync) and ships it as a sibling of
`incoming/` before arming or force-applying.

Phase 1 made failure survivable. This phase makes failure rarer, and
makes the screen tell the truth while it happens.

## Context you need

- [README.md](README.md) findings F6 and F7.
- `system/rapid-reader-ota-apply` — the whole file; it is 23 lines.
- `rapid_reader/screens.py` — `OtaScreen.tick`, after phase 1's changes.
- `rapid_reader/main.py` — `App.run`'s OTA branch; note the loop is
  single-threaded and `tick` currently blocks it.
- `system/rapid-reader.service` — `Restart=on-failure`, `RestartSec=3`,
  which is what turns a broken install into a restart loop.

## Deliverables

### 1. Validate `incoming/` before touching `/opt`

`incoming/` is whatever the last rsync left. This is a Pi Zero W on
wifi; an interrupted transfer leaves a truncated tree that the helper
currently installs with `--delete` over the live app, then restarts
into.

Have the host write a manifest alongside the staged tree (file list plus
per-file checksum — `sha256sum` over a `find | sort` is sufficient), and
have the helper verify it as its first step, refusing to proceed on any
mismatch. Per phase 0 §1, a refusal here is a clean failure that clears
`pending`, not a hang.

Also check `boot.py` and the modules it imports are present, per phase 0
§3 — a manifest proves the transfer was complete, not that the tree is
runnable.

### 2. Atomic swap with a rollback copy

Replace the in-place `rsync --delete` into the live directory with:

1. build the new tree beside the target (`/opt/rapid-reader.new`),
2. verify the phase 0 §3 invariants against it, including `splash/`
   carried over from the current install (phase 1 added the exclusion;
   here the new tree must be given a copy),
3. move the current tree aside (`/opt/rapid-reader.prev`),
4. rename the new tree into place,
5. restart the service.

Keep `.prev` for one generation. That is the rollback: if the service
fails to come up, there is a known-good tree one `mv` away, which today
does not exist in any form.

Consider having the app confirm a successful start (touch a marker after
the first successful frame) so a future phase can roll back
automatically. Specify it now even if the automatic rollback itself is
out of scope.

### 3. Stop blocking the event loop

`OtaScreen.tick` calls `subprocess.call` synchronously, freezing the
loop for the whole apply. Switch to `subprocess.Popen` and poll it from
`tick`, which the loop already calls every 0.15 s. The screen keeps
redrawing, and a hung helper stays visible instead of freezing the
device.

Add a timeout consistent with phase 0 §5's "what if the helper never
returns" decision.

### 4. Progress that measures something

Implement phase 0 §5. Either the helper reports real progress (stage
transitions at minimum: verifying → copying → swapping → restarting) and
the bar reflects it, or the bar becomes indeterminate with no
percentage.

What must go is the current arrangement: `0.2 → 0.45 → 0.7` from
hardcoded constants while nothing happens, then a freeze at 90% for the
entire real duration. If a percentage is kept, `render.progress_frame`
already takes a fraction and a label and needs no change — only its
caller does.

### 5. Tests

- manifest mismatch → helper refuses, `/opt/rapid-reader` unchanged,
  `pending` cleared,
- interrupted stage (truncate a file after staging) → refused,
- successful apply → `splash/` intact, ownership and modes per phase 0
  §3, `.prev` holds the previous tree,
- `OtaScreen` does not block: `tick` returns promptly while a stub
  helper sleeps, and the frame advances between calls,
- helper exceeds the timeout → failure path from phase 1 engages.

## Definition of done

- `python -m pytest -q` passes.
- `bash -n system/rapid-reader-ota-apply` passes; `shellcheck` clean.
- On the device: a full sync-and-apply cycle completes, the panel shows
  motion tied to real stages throughout, `/opt/rapid-reader.prev` exists
  afterwards, and the splash survives.
- Deliberately corrupting a staged file causes a clean refusal with the
  running app untouched and still functional.

## Non-goals

- Automatic rollback on failed start — specify the marker, defer the
  logic.
- Signing or authenticity checks; the manifest is for integrity, not
  trust (see phase 0 non-goals).
- Delta or resumable transfers. `rsync -az` over LAN on a tree this size
  is fine.

## Deviations from this brief, as landed

**The post-commit re-check's rollback branch has no dedicated test.**
Forcing it to actually fire would mean corrupting the live tree in the
narrow window between the two `mv`s that make up the swap — not
practically reproducible from a unit test. It is defensive code,
exercised structurally (it runs on every successful apply and passes)
but not adversarially. The pre-commit checks on `.new`, which cover the
same invariants before anything live is touched, are what the test suite
actually forces to fail.

**Ownership is a no-op under `OTA_APPLY_TEST_MODE`.** `chown -R 0:0`
needs root, which the test harness deliberately doesn't run as (matching
the pre-existing carve-out for the final `chown -R reader:reader`/
`systemctl restart`). `chmod -R a+rX` needs no such privilege and still
runs, and the post-commit ownership assertion is skipped in test mode
for the same reason as the chown itself — asserting it would just be
asserting `stat` returned this session's own UID.

**A before-commit refusal leaves `$DEST.new` on disk.** Deliberately —
matches `incoming/` already being left in place for diagnosis. The next
apply attempt starts stage 2 with `rm -rf "$NEW"` regardless, so nothing
accumulates across attempts.

## Remaining

Everything above is verified by `tests/test_ota_apply.py` (manifest
mismatch, a manifest entry for a file that vanished after staging, a
required module never staged at all, wrong-size/missing splash, missing
`incoming/`, missing manifest, `--check`, unknown-argument) and
`tests/test_app.py` (Popen-based spawn/poll/success/failure, progress-file
parsing including a torn/garbage read, the SIGTERM→SIGKILL timeout
escalation and its short-circuit if the helper exits during the grace
window). `python -m pytest -q` passes at 197 tests; `bash -n` is clean on
both shell scripts.

Still needs the device:

- A full sync-and-apply cycle against the live Pi, confirming the panel
  shows motion tied to real stages throughout (not the old canned
  animation) and that `/opt/rapid-reader.prev` exists afterward with the
  splash intact in both `/opt/rapid-reader` and `.prev`.
- Deliberately truncating a file in `incoming/` after a real
  `sync_to_pi.sh` run (killing it mid-transfer, or editing the staged
  file directly over SSH) and confirming the next apply attempt refuses
  cleanly with the running app untouched.
- Timing an actual apply on the Pi Zero W's storage to sanity-check that
  120s is comfortably generous and not, in practice, too tight.

[Phase 5](phase-5-ux-and-docs.md) is next: it depends on this phase for
its docs deliverable (describing what the progress bar now means) and
was already waiting on phases 1 and 3.
