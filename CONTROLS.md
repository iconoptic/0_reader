# Rapid Reader — Controls Reference

Two physical buttons on the Adafruit bonnet, labeled **5** and **6**
(BCM pins `PIN_BTN_5` / `PIN_BTN_6` in [rapid_reader/config.py](rapid_reader/config.py)).
Every input is either a **tap**, a **multi-tap** (2 or 3 quick taps), or a
**hold** (press and keep holding).

| Gesture      | Timing                                              |
|--------------|------------------------------------------------------|
| tap          | single press/release                                  |
| double-tap   | 2 presses within `TAP_WINDOW` (0.45 s) of each other  |
| triple-tap   | 3 presses within `TAP_WINDOW` (0.45 s) of each other  |
| hold         | held down for `HOLD_TIME` (1.5 s) before releasing    |

The app has five screens/modes: **Library**, **Reading** (playing),
**Paused**, **Confirm power-off**, and **End of book**. What each button
gesture does depends on which screen is currently shown.

## Library

The scrollable list of books found in `~/ebooks`.

| Input        | Action                                    |
|--------------|--------------------------------------------|
| 5 tap        | move selection down                         |
| 5 double-tap | move selection up                           |
| 6 tap        | open selected book (resumes last position)  |
| 6 double-tap | rescan the ebooks folder                    |
| 5 hold       | open power-off confirmation                 |

## Reading (playing)

Words are flashing automatically at the current speed.

| Input        | Action                          |
|--------------|-----------------------------------|
| 6 tap        | pause                              |
| 5 tap        | back one sentence                  |
| 5 double-tap | slower (`-25` wpm)                  |
| 6 double-tap | faster (`+25` wpm)                  |
| 6 triple-tap | forward one sentence               |
| 5 hold       | save position & return to Library  |

## Paused

Shown right after opening a book, or after pausing playback. Displays
the current sentence with the current word underlined, plus progress %
and wpm.

| Input        | Action                             |
|--------------|--------------------------------------|
| 6 tap        | resume playing                        |
| 5 tap        | back one sentence                     |
| 5 double-tap | previous chapter (if detected)         |
| 6 double-tap | next chapter (if detected)             |
| 6 triple-tap | forward one sentence                  |
| 5 hold       | save position & return to Library     |

Speed is no longer adjustable from here -- use the wpm controls while
**Reading** instead. Chapter skip is only available where a chapter/
section heading could be reliably detected in the book's text (see
below); if none were found, `5 double-tap`/`6 double-tap` do nothing.

## Confirm power-off

Reached via `5 hold` from the Library.

| Input     | Action                                    |
|-----------|----------------------------------------------|
| 6 (any)   | power off the device (safe to unplug)         |
| anything else | cancel, return to Library                 |

## End of book

Shown automatically after the last word. Any button input returns to
the Library.

## Speed limits

| Constant      | Value      |
|---------------|------------|
| `DEFAULT_WPM` | 150        |
| `MIN_WPM`     | 60         |
| `MAX_WPM`     | 450        |
| `WPM_STEP`    | 25 per tap |

## Chapter detection

When a book is opened, its text is scanned for chapter/section headings
(e.g. `Chapter 12`, `Letter 1`, `XIV`, or a bare heading like `I. A
SCANDAL IN BOHEMIA`), or, for `.epub` files, real HTML heading tags. A
bare roman numeral only counts when it stands alone, is punctuated like
a heading (`I.`) or is followed by an all-caps title, so a short
first-person paragraph such as "I went home." is not mistaken for
chapter I. This is a best-effort heuristic -- most standard Project
Gutenberg books are detected reliably, but books with unusual formatting
may have some, few, or no chapters detected. When none are found, the
chapter-skip bindings in **Paused** simply do nothing.

## Fast reading (multi-word chunks)

At higher wpm the panel can't refresh fast enough to show one word per
frame, so several words are shown at once. Each word still gets its own
bold pivot letter (like single-word mode) as long as the whole chunk
fits on one line without cutting any word off; if it wouldn't fit, the
chunk falls back to plain (un-highlighted) text instead of truncating a
word.
