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
**K3** is the context-action key on list screens (delete bookmark, delete
book, …); elsewhere it is a no-op unless noted.

## Library

Scrollable list of books in `~/ebooks`.

| Input | Action |
|-------|--------|
| up / down (repeat) | move selection |
| left / right (repeat) | page by one screenful |
| press | open selected book (resumes last position) |
| K1 hold | open power-off confirmation |
| K2 tap | main menu |
| K3 tap | book info for the highlighted book |

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

Chapter skip only works where a heading could be detected in the book
(see below); otherwise those holds do nothing.

## List screens

Chapters, bookmarks, settings, themes, system, and the book menu share
the same skeleton:

| Input | Action |
|-------|--------|
| up / down (repeat) | move selection |
| press | select / activate the highlighted row |
| K1 | back one level |
| K3 | context action when one exists (e.g. delete bookmark / delete book); otherwise no-op |

## Idle

On any screen **except Reading**: no input for `IDLE_DIM_SECS` (60 s)
drops contrast to `IDLE_DIM_CONTRAST`; no input for `IDLE_OFF_SECS`
(300 s) puts the panel to sleep. Any key press wakes the panel and is
**swallowed** — it is not passed to the active screen's handler.

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
