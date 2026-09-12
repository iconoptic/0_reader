# Phase 0 — OTA contracts

**Status:** done. **Depends on:** nothing. **Parallel with:**
phase 2.

The step that was skipped. Nothing in phases 1, 3 or 4 should be written
until this file's tables are filled in and reviewed, because all three
touch the same state machine from different sides (app, host script,
root helper) and the current tree's bugs are all disagreements between
those three views.

This phase writes **no code**. Its deliverable is this document, edited
in place with the decisions made.

## Context you need

- `rapid_reader/config.py:49-53` — the existing `OTA_*` constants.
- `rapid_reader/main.py` — `App._check_ota`, and the `run` loop's two
  arms (`get_nowait` while reading, `get(timeout=1.0)` otherwise).
- `rapid_reader/screens.py` — `OtaScreen`.
- `system/rapid-reader-ota-apply`, `tools/sync_to_pi.sh`.
- `tools/build_card.sh:276-303` — how `/opt/rapid-reader` is laid out and
  what the build asserts about it.

## Deliverables

### 1. On-device OTA state, as files

All paths below live under `/var/lib/rapid-reader/ota/` (i.e.
`config.OTA_DIR`). Ownership of the directory tree is `reader:reader`;
only the helper (root) may rewrite it when applying.

| Path | Written by | Read by | Meaning | Removed by |
|---|---|---|---|---|
| `incoming/` | host sync (`sync_to_pi.sh` rsync) | helper | staged app tree; may be partial until `manifest` verifies | helper on successful apply (emptied and recreated); host sync replaces contents on next sync |
| `pending` | host sync (after a successful preflight + stage) | app (`_check_ota`) | an apply is armed; presence alone is the trigger | **app, immediately before invoking the helper**; helper also `rm -f`s it on success (idempotent) |
| `failed` | app (on non-zero helper exit, timeout, or spawn failure) | app (`_check_ota`, failed-screen label) | last apply failed; do not auto-retry. `_check_ota` must not push `OtaScreen` while this file exists, even if `pending` is also present | host sync, when it arms a *new* update (clears `failed` in the same step that writes `pending`) |
| `manifest` | host sync (after `incoming/` rsync completes) | helper | complete file list + per-file sha256 of what `incoming/` must contain; sibling of `incoming/`, not inside it | helper on successful apply; host sync overwrites on each app sync |
| `progress` | helper (while running) | app (`OtaScreen.tick`) | current apply stage for the UI (see §5) | helper on exit (success or failure); app may also unlink on entering the failed state |

#### Who clears `pending` on failure

**Decision: the app clears `pending` immediately before invoking the
helper.**

Rationale: fail-open. A crashed, killed, or never-started helper must
not leave the device in a boot loop (F1). Clearing before the call covers
the device's current state (helper absent → `sudo -n` fails immediately)
and mid-rsync kills / power loss after the invoke has begun.

Consequences:

- On failure the app writes `failed` (contents: UTC timestamp, exit
  status or `"timeout"` / `"spawn"`, one short reason line).
- On success the service is restarted by the helper; the app process
  does not continue. The helper still removes `pending` and `failed` as
  belt-and-braces before restart.
- Do **not** clear `pending` only on helper success — that is today's
  bug.

Power loss *after* arming and *before* the app clears `pending` still
re-enters OTA once on next boot; that is intentional (one automatic
attempt). After the clear, there is no second automatic attempt.

### 2. The escape hatch

**Decision:**

- **Dismiss input:** `k1` **tap** dismisses only when the screen is in
  the *failed* state. In-progress continues to swallow every event
  (including `k1`). This matches the stable role "K1 = Back / leave"
  and cannot be confused with confirm (`k3`) or menu (`k2`).
- **After dismissal:** call `App.pop_to_root()` so the stack is a single
  `LibraryScreen`. The installed tree under `/opt/rapid-reader` is
  whatever survived the failed apply (pre-phase-4: still the old tree if
  the helper never ran; possibly damaged if it died mid-rsync — phase 4
  shrinks that window). Do not attempt a second apply from the dismiss
  path.
- **Idle:** in-progress bypasses `_tick_idle()` (no dim, no sleep) so the
  panel stays readable for the whole apply. Failed rejoins normal idle
  handling (`IDLE_DIM_SECS` / `IDLE_OFF_SECS`); any wake-on-input still
  swallows the waking press before `handle` sees it, same as every other
  non-reading screen.

### 3. Apply-time invariants for `/opt/rapid-reader`

After a successful apply, `/opt/rapid-reader` must satisfy everything
`build_card.sh` already guarantees for a fresh card:

1. `splash/` exists and `splash/splash.bin` is exactly 1024 bytes.
2. Ownership `0:0`, mode `a+rX` on the tree.
3. `boot.py` is present, and every module on the boot/import path used by
   the card-build verify step is present and non-truncated:
   `config`, `display`, `oled`, `render`, `rsvp`, `books`, `theme`,
   `main` (and their transitive in-tree imports). A verified `manifest`
   proves transfer completeness; this list proves the tree is the app,
   not an arbitrary directory.

`splash/` is **not** shipped in `incoming/`. The helper must preserve the
live `splash/` (phase 1: `--exclude 'splash/'` on the live rsync; phase 4:
copy splash from the current tree into the staging `.new` tree before
commit). Host sync's `--exclude 'splash/'` on the repo→`incoming` rsync
stays, but it is not the splash-protection boundary — the helper is.

**When checked:**

| Invariant | Before commit (refuse to switch live tree) | After commit (before `systemctl restart`) |
|---|---|---|
| `manifest` matches `incoming/` | yes | n/a (staging consumed) |
| required modules present in the tree about to go live | yes | no (already gated) |
| `splash/splash.bin` present and 1024 bytes in the tree about to go live | yes | yes (re-check; violation → failed apply, do not restart) |
| ownership `0:0`, mode `a+rX` | no (apply them as part of commit) | yes (helper runs `chown`/`chmod`, then confirms) |

A before-commit failure is a clean refuse: no live-tree mutation (phase
4) / no restart; `pending` already cleared by the app; helper exits
non-zero; app writes `failed`.

### 4. Host→device preflight contract

**Decision: refuse to write `pending` when preflight fails.** Stage
`incoming/` / `manifest` only after the checks that do not need a fresh
stage pass; write `manifest`, then run the full preflight, then write
`pending` (and clear `failed`). Never arm an apply the device cannot
run.

Preflight remote commands (via existing `ssh_pi` / `BatchMode=yes`), all
must succeed:

| Check | Remote command |
|---|---|
| Helper present and executable | `test -x /usr/local/sbin/rapid-reader-ota-apply` |
| Sudoers rule effective + helper sane | `sudo -n /usr/local/sbin/rapid-reader-ota-apply --check` (no-op: verifies incoming/manifest readable or reports "not staged", exits 0 only if the binary runs under NOPASSWD and basic paths exist; must not apply) |
| App on device understands `pending` | `python3 -c 'import sys; sys.path.insert(0,"/opt/rapid-reader"); import config; assert config.OTA_PENDING.endswith("/ota/pending")'` |

On any failure: print which check failed, tell the operator to run
`tools/sync_to_pi.sh --bootstrap` (or install the helper by hand), exit
non-zero, leave `pending` absent. Do not warn-and-arm.

`--force-apply` still requires the same preflight; it is not an escape
from it. `--bootstrap` is the path that installs the missing pieces,
then re-runs sync with preflight.

### 5. Progress semantics

**Decision: stage-based progress, not a wall-clock percentage.**

The helper writes `progress` as a single line, replaced atomically
(write temp + `mv`):

```text
<current>/<total> <stage-name>
```

Stages, in order (`total` = 4):

1. `verifying` — manifest + required-module checks
2. `copying` — build the new tree (in-place rsync in phase 1; populate
   `.new` in phase 4)
3. `committing` — ownership/mode, splash re-check, swap into place
4. `restarting` — about to `systemctl restart`

The app maps `current/total` to the progress fraction and shows
`stage-name` (or a short label derived from it). No synthetic
`0.2 → 0.45 → 0.7` animation. If `progress` is missing mid-apply, show
an indeterminate busy label (`Updating...`) with fraction 0 — never a
fake percent.

**Event loop:** `OtaScreen` starts the helper with `subprocess.Popen`
and returns from `tick` promptly; each tick polls the process and
re-reads `progress`. The main loop keeps its 0.15 s OTA cadence.

**Helper never returns:** after **120 seconds** wall time from spawn,
the app sends `SIGTERM`, waits briefly, then `SIGKILL` if needed, treats
the attempt as failed (write `failed` with reason `timeout`; `pending`
was already cleared at spawn). 120 s is generous for a whole-tree copy
on a Pi Zero W over local storage; it is a hard cap so a wedged helper
cannot hold the non-dismissible in-progress screen forever.

## Definition of done

- Every `?` in the table above is filled in.
- Sections 2–5 each end in a decision, not a list of options.
- The decisions are internally consistent: no path is written by two
  owners, and every file that can be created has a named remover.
- No file under `rapid_reader/`, `tools/`, or `system/` is modified.

## Non-goals

- Signing, verification, or any trust model for the update payload. This
  is a LAN sync to a device on the user's own network; scope it there.
- Delta updates. The tree is small; whole-tree replacement is correct.
- Supporting OTA of anything outside `/opt/rapid-reader` (the service
  file, sudoers, kernel config). Those stay card-build territory.
