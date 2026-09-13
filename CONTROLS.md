# Rapid Reader — Controls Reference

Eight inputs on the 1.3" SH1106 OLED HAT: a **5-way joystick** and three
keys **K1** / **K2** / **K3**. BCM pins live in `config.PINS` (see
[rapid_reader/config.py](rapid_reader/config.py)). Every input is a
**tap**, a **hold**, or a **repeat** while held.

| Gesture | Timing |
|---------|--------|
| tap | press and release before `HOLD_DELAY` (0.5 s) |
| hold | held past `HOLD_DELAY` on a non-repeating key (fires once) |
| repeat | held past `HOLD_DELAY` on a repeating key (`up`/`down`/`left`/`right`); first event then every `REPEAT_SECS` (0.12 s) until release |

Repeating keys never emit a separate `hold` event — only `repeat`.

Stable key roles:

| Key | Role |
|-----|------|
| **K1** | Back / leave. Hold on Library only = power-off confirm. |
| **K2** | Menu (everywhere). |
| **K3** | Act: pause/resume, confirm-yes, list context when one exists. |

## Library

Scrollable browse of `~/ebooks`. Subdirectories appear as folder menus
(name followed by `/`); press opens the folder. Supported files
(`.txt` / `.epub`) at any depth are books. Nested folders work the same
way to any depth. If the highlighted name is truncated, it scrolls left
after 1 s so the rest of the title is visible.

| Input | Action |
|-------|--------|
| up / down (repeat) | move selection |
| left / right (repeat) | page by one screenful |
| press | open selected folder or book (book resumes last position) |
| K1 tap | back one folder (no-op at library root) |
| K1 hold | open power-off confirmation (library root only) |
| K2 tap | main menu |
| K3 tap | book info for the highlighted book (books only) |

## Reading (playing)

Words flash automatically at the current speed.

| Input | Action |
|-------|--------|
| press or K3 tap | pause |
| up / down tap | wpm ± `WPM_STEP` (flashes briefly in a corner) |
| left / right tap | jump one sentence back / forward |
| K1 tap | save position and return to Library |
| K2 tap | open book menu |

## Paused

Shown right after opening a book, or after pausing. Same bindings as
**Reading**, plus:

| Input | Action |
|-------|--------|
| left / right hold (repeat) | jump one chapter back / forward |
| up / down tap | wpm ± `WPM_STEP`; brief overlay shows remaining time (d/h/m/s) |

Chapter skip only works where a heading could be detected in the book
(see below); otherwise those holds do nothing.

## List screens

Chapters, bookmarks, settings, themes, system, and the book menu share
the same skeleton. Truncated highlighted rows scroll left after 1 s
(same as Library).

| Input | Action |
|-------|--------|
| up / down (repeat) | move selection |
| left / right (repeat) | page by one screenful |
| press | select / activate the highlighted row |
| K1 | back one level |
| K2 | open menu (no-op when already on the menu) |
| K3 | context action when one exists (e.g. delete bookmark); otherwise no-op |

## Menus (K2)

K2 opens a list menu. Contents depend on whether a book is open:

| Context | Items |
|---------|-------|
| Library (no book open) | Settings, System |
| Reading / Paused / in-book lists | Bookmark this page, Chapters, Bookmarks, Book info, Settings, System, Save & close book |

- **Bookmark this page** — saves the current word index, then pops back.
- **Chapters** / **Bookmarks** / **Book info** — push the corresponding screen.
- **Save & close book** — same as leaving to Library (position saved).
- **End of book** — any key clears the in-memory book and returns to the Library (so K2 there shows the short menu again).

## Settings

Press on a row activates it. Word size and pivot style **cycle** through
their values and save immediately; Theme and Display push sub-screens.

| Row | Behavior |
|-----|----------|
| Word size | Cycles `small` → `medium` → `large` |
| Pivot style | Cycles `ticks` → `underline` → `box` → `bold` |
| Theme | Opens the theme picker |
| Display | Opens session contrast adjust |

Defaults (`config.SETTINGS_DEFAULTS`): theme `night`, pivot `ticks`, word size `medium`, wpm `DEFAULT_WPM`.

## Themes

Presets from `theme.THEMES`. Selecting one applies it, keeps your
current pivot-style override, and returns to Settings. Active theme is
marked with `*`.

| Key | Name | Invert | Font | Default pivot | Contrast |
|-----|------|--------|------|---------------|----------|
| `night` | Night | no | sans | ticks | `0xCF` |
| `paper` | Paper | yes | serif | underline | `0xCF` |
| `focus` | Focus | no | sans | box | `0xFF` |
| `dim` | Dim | no | mono | bold | `0x40` |
| `mono` | Mono | no | mono | ticks | `0xCF` |

Pivot style in Settings overrides the theme's default pivot for drawing;
changing theme does not reset a custom pivot style.

## Display (contrast)

Session-only contrast nudge (not written to `state.json`):

| Input | Action |
|-------|--------|
| up / down (repeat) | contrast ± `0x10` (clamped 0–255) |
| K1 tap | back (keeps the nudge for this session) |

Resets to the active theme's contrast on the next theme change or app
restart. Idle dim/off still apply on top of this while idle.

## System

| Row | Action |
|-----|--------|
| IP address | Shows the device IP (or `no network`) |
| Disk free | Free space under the books directory |
| Version | `config.VERSION` |
| Screen test | Full-screen all-on / all-off / 1px checkerboard; press/up/down cycles; K1 back. Stays at full contrast (idle dim/off suppressed) until you leave. |
| Reboot | Confirm, then reboot |
| Power off | Confirm, save state, then power off |

Reboot and power-off use `sudo -n` when not running as root (passwordless
sudo on the appliance image). OTA apply uses the same pattern for
`/usr/local/sbin/rapid-reader-ota-apply`.

## OTA updates

`tools/sync_to_pi.sh` stages under `/var/lib/rapid-reader/ota/incoming/`,
writes a sibling `manifest`, and — after preflight — arms
`ota/pending` (or `--force-apply` installs over SSH without arming).
The running app detects `pending`, wakes the panel if asleep, and pushes
a non-dismissible progress screen.

The bar tracks real helper stages written to `ota/progress`
(`verifying` → `copying` → `committing` → `restarting`), not a
synthetic animation. Input is ignored while the apply is in progress.
On success the service restarts into the new tree.

**On failure** the screen shows `Update failed (...)`. Tap **K1** to
dismiss it and return to the library. A failure marker at `ota/failed`
prevents auto-retry across reboots until the next successful host sync
clears it. Idle dim/off apply again on the failed screen.

## Bookmarks

| Input | Action |
|-------|--------|
| press | jump to that word index and return to Paused |
| K3 | confirm delete of the highlighted bookmark |

Empty list shows: `No bookmarks yet.` / `Menu > Bookmark this page`.

## Confirm dialogs

| Input | Action |
|-------|--------|
| K3 tap | yes |
| K1 tap | no |
| other keys | ignored |

Used for power-off (Library K1 hold or System), reboot, and bookmark
delete.

## Idle

On any screen **except Reading**, **Screen test**, and an **in-progress
OTA** update: no input for `IDLE_DIM_SECS` (60 s) drops contrast to
`IDLE_DIM_CONTRAST`; no input for `IDLE_OFF_SECS` (300 s) puts the panel
to sleep. Any key press wakes the panel and is **swallowed** — it is not
passed to the active screen's handler. A failed OTA screen rejoins
normal idle handling.

## Speed limits

| Constant | Value |
|----------|-------|
| `DEFAULT_WPM` | 250 |
| `MIN_WPM` | 60 |
| `MAX_WPM` | 900 |
| `WPM_STEP` | 25 |

## Chapter detection

When a book is opened its text is scanned for chapter/section headings
(`Chapter 12`, `Letter 1`, `XIV`, or a bare heading like `I. A SCANDAL
IN BOHEMIA`); for `.epub` files real HTML heading tags are used instead.
A bare roman numeral only counts when it stands alone, is punctuated
like a heading (`I.`) or is followed by an all-caps title, so "I went
home." is not mistaken for chapter I. This is a best-effort heuristic:
most Project Gutenberg books are detected reliably; unusual formatting
may yield few or no chapters.

## Fast reading (multi-word chunks)

If a frame ever takes longer to render and push than the word's delay
(the OLED itself refreshes in a few milliseconds, so this only happens
at extreme wpm), several words are shown at once so the *average* pace
still matches. Each word keeps its own accent pivot letter as long as
the chunk fits on one line; otherwise it falls back to plain text rather
than cutting a word off.
