# Rapid Reader — plan_1: OTA / sync untangle

**Status: landed.** This directory is the historical roadmap for the work
that followed the SH1106 overhaul ([plan_0/](../plan_0/), landed and
historical). For current sync/OTA behaviour, use the root
[README.md](../../README.md) and [CONTROLS.md](../../CONTROLS.md) — not
the per-phase status lines inside the briefs below.

## Why this directory exists

The feature request that produced the working tree asked for three
things:

1. a remaining-time overlay when wpm changes on the pause screen,
2. a dead-pixel screen test in the System menu,
3. a host→Pi sync script, plus an in-app OTA hook that interrupts
   whatever is running, shows a progress bar, and restarts into the new
   code.

Items 1 and 2 were small and mostly correct on first pass. Item 3
introduced a root-privileged helper, a new sudoers rule, a
non-dismissible screen, and a trigger that fires before the user
touches anything — written with no contract doc. plan_0 had pinned
every signature before coding; the OTA work skipped that and produced
designs that could not succeed on the target hardware (F3), could not
recover when they failed (F1), and quietly destroyed device state when
they succeeded (F2). This directory is the gap review and the six phase
briefs that fixed it.

## What is actually fine

Do not rewrite these; they were not the problem (F8/F9 polish landed in
phase 5).

- **Remaining-time overlay.** `App.change_wpm` branches on
  `PausedScreen` and formats via `render.fmt_duration_hms`
  (days/hours/minutes/seconds, leading zero units omitted);
  `render.remaining_overlay` draws a centred inverted band using the
  active theme. `ReadingScreen` keeps the corner `"%d wpm"` flash.
- **Screen test.** `ScreenTestScreen` cycles all-on / all-off / 1px
  checkerboard at `config.OLED_W`/`OLED_H`, holds
  `IDLE_ACTIVE_CONTRAST`, and suppresses idle dim/off while on top.
- **`pop_to_root` hardening.** Forces the stack back to a
  `LibraryScreen` root; three tests.
- **`_check_ota` polling placement.** Both loop arms return to the top
  of the loop, so pending is detected within ~1 s on any screen.

## Findings

Severity is about the device, not the code. **What landed** notes what
phases 0–5 actually shipped vs the original brief.

| # | Sev | Finding | What landed |
|---|-----|---------|-------------|
| F1 | **Critical** | A failed OTA hangs the device permanently, and survives a power cycle. | Fixed as specified (phase 1): dismissible failure, `ota/failed` marker, pending cleared before spawn. |
| F2 | **High** | The first successful OTA deletes the boot splash. | Fixed as specified (phase 1): helper preserves/carries `splash/` across apply. |
| F3 | **High** | `--bootstrap` cannot work on any already-flashed card, by construction. | Fixed as specified (phase 3): interactive `ssh -t` sudo; see also the phase-3 deviation note (app-version preflight does not gate `--force-apply`). |
| F4 | **High** | Host SSH config was written into the device-provisioning directory; its current location is not gitignored. | Fixed as specified (phase 2): repo-root `pi.env` + gitignore. |
| F5 | **Medium** | `sync_to_pi.sh` arms an OTA without checking the device can apply it. | Fixed as specified (phase 3): preflight before arming; refuses and names `--bootstrap`. |
| F6 | **Medium** | `--delete` install from an unvalidated staging tree; no atomicity, no rollback. | Fixed as specified (phase 4): manifest verify, `$DEST.new` / `.prev` swap, post-swap rollback. |
| F7 | **Medium** | The progress bar is theatre and blocks the event loop. | Fixed as specified (phase 4): `Popen` + poll; bar maps `ota/progress` stages. |
| F8 | **Low** | The screen test blanks itself mid-test. | Fixed as specified (phase 5), plus a third checkerboard mode. |
| F9 | **Low** | The remaining-time overlay ignores the active theme. | Fixed as specified (phase 5): `theme` param; single `_finalize`. |
| F10 | **Low** | README/CONTROLS document the intended flow as if it worked. | Fixed as specified (phase 5): docs rewritten against the landed sync/OTA behaviour. |

### F1 — A failed OTA bricks the device (critical)

`screens.OtaScreen.handle` is `pass` — it swallows every event by
design. On failure `tick` sets `self._failed = True`, after which `tick`
returns immediately. `main.App.run`'s OTA branch `continue`s *before*
`_tick_idle()`, so the panel never dims or sleeps either. The device
sits on "Update failed" forever, accepting no input.

It does not end at a power cycle. `system/rapid-reader-ota-apply` runs
under `set -euo pipefail` and only reaches `rm -f "$PENDING"` after a
successful rsync — so a failure leaves `pending` in place. On the next
boot `_check_ota` finds it and pushes `OtaScreen` again. **Failed OTA →
permanent boot loop into a dead screen**, recoverable only over SSH or
by re-flashing.

The Pi is in exactly the state that triggers this: the helper was never
installed, so `subprocess.call(["sudo", "-n", config.OTA_APPLY])` returns
non-zero on the first try. The only reason this has not fired yet is
that the Pi still runs pre-OTA code that ignores `pending` — i.e. the
bug is armed and waiting for the very update that would deliver it.

> **Operational note:** do not run `tools/sync_to_pi.sh` (with or without
> flags) against the device until [phase-1](phase-1-recovery.md) lands.
> The plain form writes `pending` unconditionally.

### F2 — The first OTA deletes the boot splash (high)

`tools/build_card.sh:276-279` installs the app with `--exclude 'splash/'`
and *then* generates `/opt/rapid-reader/splash/splash.bin` (the build
even asserts it is exactly 1024 bytes at line 301-303). `splash/` is
gitignored and exists only on the device.

`system/rapid-reader-ota-apply` rsyncs `--delete` from `incoming/` into
`/opt/rapid-reader/` with **no** splash exclusion, so the first apply
removes `splash/`. `tools/sync_to_pi.sh:95` carries a comment reading
"Keep device splash" — the exclusion was on the author's mind but landed
on the host→`incoming` rsync, where it was never the thing at risk,
rather than on the `incoming`→`/opt` rsync, where it was.

Not a brick: `boot.py:25` tolerates the absence and prints `boot: no
splash image in ...`. But the splash is unrecoverable short of a card
rebuild, and every subsequent OTA re-deletes it.

### F3 — `--bootstrap` cannot bootstrap (high)

`tools/sync_to_pi.sh:61` gates the whole install on:

```sh
if ! ssh_pi 'sudo -n true' 2>/dev/null; then ... exit 1; fi
```

On a card built before this change, `/etc/sudoers.d/010_rapid-reader`
grants NOPASSWD for `/usr/sbin/poweroff` and `/usr/sbin/reboot` only, so
`sudo -n true` is denied and always will be. That is not an edge case —
it is the definition of the population `--bootstrap` exists to serve. A
card new enough to pass the check already has the helper installed by
`build_card.sh` and never needed bootstrapping.

So the flag does nothing but `scp` a file to `/tmp`, print a block of
manual instructions, and `exit 1`. That is precisely the transcript the
user saw. The closing line, "Then re-run: `tools/sync_to_pi.sh
--bootstrap`", asks the user to re-run a command whose entire payload
they have just performed by hand.

The route out was available the whole time: `build_card.sh:168-175` sets
a real password for `reader` (salvaged from `ssh_salvage/password`, else
literally `reader`). `ssh -t "$PI_SSH" sudo ...` prompts for it
interactively and installs the helper in one pass. `BatchMode=yes` on
every call in this script is what forecloses that option.

### F4 — Secrets in the device-provisioning directory (high)

`ssh_salvage/` is the staging area for material that goes **onto the
card**: `home/authorized_keys` → the Pi's `~/.ssh/authorized_keys`
(`build_card.sh:178`), `wifi.env` → the Pi's NetworkManager profile
(`:197`), `password` → the Pi's `reader` password (`:168`), plus
`state.json` and `rfkill/`. Host-side "how do I reach the Pi" config
points the other way and does not belong in it.

To be precise about blast radius: `build_card.sh` reads named files, not
the whole directory, so a stray `pi.env` there was never copied to the
card. The error is categorical, not a live leak — but it is the kind of
error that only comes from not knowing which direction the directory
points, which is the same gap that produced F2 and F3.

The file's current location is the more urgent half. `./pi.env` is
**not** matched by any `.gitignore` rule (`ssh_salvage/` is ignored;
plain `pi.env` is not), leaving it one `git add -A` from being
committed. And `sync_to_pi.sh:15` still reads `$HERE/ssh_salvage/pi.env`,
so the file the user moved is not the file the script loads. Neither
location is right.

### F5 — Arming an OTA the device cannot apply (medium)

`sync_to_pi.sh:110-113` writes `pending` whenever the app was synced,
with no check that `/usr/local/sbin/rapid-reader-ota-apply` exists, that
the sudoers rule allows it, or that the running app even understands
`pending`. The helper check at `:119` happens only under
`--force-apply`, i.e. only on the path that does not need it. Arming the
trigger is the default; verifying it can fire is opt-in.

### F6 — Unvalidated `--delete` install, no rollback (medium)

`incoming/` is whatever the last rsync left behind. An interrupted
transfer (this is a wifi-attached Pi Zero W) leaves a truncated tree that
`ota-apply` then installs over the live `/opt/rapid-reader` with
`--delete` and restarts the service. There is no manifest, no checksum,
no atomic directory swap, and no previous-version copy to fall back to.
A half-written `main.py` yields a unit that fails, gets restarted by
`Restart=on-failure`, and fails again — with `pending` still present, so
F1 applies on top.

### F7 — The progress bar is theatre (medium)

`OtaScreen.tick` walks `0.2 → 0.45 → 0.7` through hardcoded constants at
one step per 0.15 s, then jumps to 0.9 and calls `subprocess.call`
**synchronously**, blocking the event loop for the real, unbounded
duration of the rsync and `systemctl restart`. The bar moves when
nothing is happening and freezes solid while the actual work runs. The
request asked for a progress bar; this is its silhouette.

### F8 — The screen test blanks itself (low)

`ScreenTestScreen` is not a `ReadingScreen`, so the loop takes the
`get(timeout=1.0)` arm and calls `_tick_idle()` every second. At
`IDLE_DIM_SECS = 60` the panel drops to `IDLE_DIM_CONTRAST = 0x20`; at
`IDLE_OFF_SECS = 300` it sleeps. A dead-pixel test that dims after a
minute and switches off after five, while the user is staring at it
looking for dim pixels. It also inherits the theme's contrast, when an
all-pixels-on field is the one case that wants maximum.

### F9 — Overlay ignores the active theme (low)

`render.paused_frame` receives `theme` and uses it for every glyph it
draws, then calls `remaining_overlay`, which calls `_default_theme()`
and picks its own face. On any non-default theme the badge is set in a
different family from the text it covers. It also runs `_finalize` twice
(once before the overlay, once after) — harmless, but it signals the
overlay was bolted on rather than folded into the frame.

### F10 — Docs describe the aspiration (low)

The README section added by this change says "After that, plain
`tools/sync_to_pi.sh` is enough — the in-app OTA UI handles the rest",
and CONTROLS.md gained an "OTA updates" section in the present tense.
None of it has run on hardware. The README's own bootstrap section
concedes the point — it opens with manual `scp`/`ssh`/`sudo` steps and
only then mentions `--bootstrap`, which is an admission that the flag
does not bootstrap. Docs for unexercised paths should say so.

Also: the seven new tests cover happy paths only
(`test_ota_pending_wakes_and_applies` monkeypatches a successful apply).
There is no test for a failing helper, and it is the failure path that
bricks the device.

## Phases

Ordered so that device safety lands first and nothing depends on a later
phase. Phases 1–2 are independently shippable and worth landing before
any new OTA behaviour is attempted.

| Phase | Brief | Fixes | Depends on | Status |
|---|---|---|---|---|
| 0 | [phase-0-ota-contracts.md](phase-0-ota-contracts.md) | — | — | ✅ done |
| 1 | [phase-1-recovery.md](phase-1-recovery.md) | F1, F2 | 0 | ✅ done |
| 2 | [phase-2-secrets-and-config.md](phase-2-secrets-and-config.md) | F4 | — | ✅ done |
| 3 | [phase-3-bootstrap.md](phase-3-bootstrap.md) | F3, F5 | 0, 2 | ✅ done |
| 4 | [phase-4-atomic-apply.md](phase-4-atomic-apply.md) | F6, F7 | 0, 1 | ✅ done |
| 5 | [phase-5-ux-and-docs.md](phase-5-ux-and-docs.md) | F8, F9, F10 | 1, 3, 4 | ✅ done |

Phase 2 touches only gitignore/docs/one path constant and can run in
parallel with 0 and 1. Phase 5's doc portion must land last, since it
describes the finished behaviour.

## Suggested agent sizing

Following plan_0's convention of saying which phases are safe to hand to
a small, fast model:

| Phase | Nimble? | Why |
|---|---|---|
| 0 — Contracts | **Yes** | Pure spec transcription; no judgment left once written. |
| 1 — Recovery | **No** | Touches the failure semantics of a non-dismissible screen and the boot path. Wrong here means a bricked device. |
| 2 — Secrets/config | **Yes** | Mechanical: one path constant, two gitignore lines, a doc edit. |
| 3 — Bootstrap | **Conditional** | Shell + interactive SSH + sudo. Mechanical once phase 0 pins the preflight contract, but untestable without the device — pair it with a manual run. |
| 4 — Atomic apply | **No** | Atomic swap, rollback, and a non-blocking apply in a single-threaded loop; several interacting failure modes. |
| 5 — UX/docs | **Yes** | Small, local, well-specified diffs against a finished implementation. |
