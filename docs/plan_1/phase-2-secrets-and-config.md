# Phase 2 — Secrets and config location

**Status:** done. **Depends on:** nothing. **Parallel with:**
phases 0 and 1. **Fixes:** F4 (high).

Small and mechanical, but do it early: the current state has an
un-ignored file holding the device's SSH target sitting in the repo
root, and the script that wants it is looking somewhere else.

## Context you need

- [README.md](README.md) finding F4.
- `tools/build_card.sh:168-175, 178, 197-201, 293-295` — every place
  `ssh_salvage/` is consumed, to see which direction the directory
  points.
- `tools/sync_to_pi.sh:14-15, 38-44` — where the env file is read.
- `.gitignore` — `ssh_salvage/` is ignored; plain `pi.env` is not.
- `README.md` — the "Syncing to a live Pi (OTA)" section documents
  `ssh_salvage/pi.env`.

## The distinction to preserve

`ssh_salvage/` is **inbound to the card**. `build_card.sh` reads named
files from it and writes them into the image: `home/authorized_keys` →
the Pi's `~/.ssh/authorized_keys`, `wifi.env` → the Pi's NetworkManager
profile, `password` → the Pi's `reader` password, `state.json` → the
Pi's saved reading state. Anything placed there is, by the directory's
contract, a thing that ends up on the device.

Host-side connection config points the other way: it is how *this
workstation* reaches an already-running Pi. It is not card-build input
and must not live in the card-build input directory, even though
`build_card.sh` reads by name and would not have copied it.

## Deliverables

### 1. Choose one host-config location and use it everywhere

Recommendation: `./pi.env` at the repo root, which is where the user
already moved it. It is host-side config for a host-side script, it sits
next to the script's natural working directory, and it keeps the
device-inbound directory single-purpose.

Update `tools/sync_to_pi.sh:15` (`ENV_FILE`) to match, and update the
usage block at the top of the script (lines 2-11), which also names
`ssh_salvage/pi.env`.

If you would rather keep it out of the root, `.pi.env` or `local/pi.env`
are fine — but pick one, and make the script, `.gitignore`, the usage
text and the README agree. Four places, all currently disagreeing in
some combination, is what produced this finding.

### 2. Ignore it

Add the chosen path to `.gitignore`. Verify with `git check-ignore -v
pi.env` that the rule actually matches — the current `ssh_salvage/` rule
does not cover a root-level `pi.env`, which is why the file is presently
one `git add -A` from being committed.

Confirm nothing already tracked contains the host or credentials:
`git log -p -S '192.168' -- . | head` and `git grep -n '192\.168'`
against the tree.

### 3. Fail usefully when it is missing

The current error (`missing ... — create it with PI_SSH=reader@host`) is
fine in shape. Extend it to state that the file is gitignored and
host-side, so the next reader does not re-derive this phase. Keep the
`PI_SSH` unset check.

### 4. Ship an example, not a secret

Add a tracked `pi.env.example` with `PI_SSH=reader@raspberrypi.local`
and a one-line comment saying the real file is gitignored. This is the
usual way to make the requirement discoverable without committing the
value.

### 5. Correct the docs

Update the README's "Syncing to a live Pi (OTA)" section to name the
chosen path and say why it is not in `ssh_salvage/` — one sentence, so
the distinction survives. Do not touch the rest of that section yet; its
claims about the OTA flow are phase 5's problem.

## Definition of done

- `git check-ignore -v <chosen path>` reports a matching rule.
- `grep -rn 'ssh_salvage/pi.env' .` returns nothing outside
  `docs/plan_1/`.
- `tools/sync_to_pi.sh` loads the user's existing file with no manual
  move, and its `--help` output names the same path.
- `git grep -n '192\.168'` finds nothing in tracked files.
- `bash -n tools/sync_to_pi.sh` passes.

## Non-goals

- Reorganising `ssh_salvage/` itself, or changing anything
  `build_card.sh` reads from it.
- SSH key management, agent forwarding, or multi-device support. One
  target, one variable.
