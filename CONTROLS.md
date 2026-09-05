# Rapid Reader — Controls Reference

Two physical keys on the right edge of the Waveshare Zero LCD HAT (A):
**K1** (upper, BCM 25) and **K2** (lower, BCM 26); see `PIN_KEY1` /
`PIN_KEY2` in [rapid_reader/config.py](rapid_reader/config.py). Every
input is a **tap**, a **multi-tap** (2 or 3 quick taps) or a **hold**.

| Gesture     | Timing                                               |
|-------------|------------------------------------------------------|
| tap         | single press/release                                 |
| double-tap  | 2 presses within `TAP_WINDOW` (0.45 s) of each other |
| triple-tap  | 3 presses within `TAP_WINDOW` (0.45 s) of each other |
| hold        | held down for `HOLD_TIME` (1.5 s) before releasing   |

Rule of thumb: **K1 goes forward** (open, play, faster, next) and **K2
goes back** (down the list, previous, slower, leave). The right-hand
side screen always shows the bindings for the current screen, so you
never have to memorise this page.

The app has five modes: **Library**, **Reading**, **Paused**, **Confirm
power-off** and **End of book**.

## Library

Main screen: scrollable list of the books in `~/ebooks`. Left screen:
card for the highlighted book (format, position, length, saved wpm).
Right screen: key hints.

| Input         | Action                                    |
|---------------|-------------------------------------------|
| K1 tap        | open selected book (resumes last position)|
| K1 double-tap | rescan the ebooks folder                  |
| K2 tap        | move selection down                       |
| K2 double-tap | move selection up                         |
| K2 hold       | open power-off confirmation               |

## Reading (playing)

Words flash automatically at the current speed. The side screens are
dimmed to `BL_SIDE_READING`; the left one shows progress / time
remaining / chapter, the right one shows the current wpm.

| Input         | Action                            |
|---------------|-----------------------------------|
| K1 tap        | pause                             |
| K1 double-tap | faster (`+25` wpm)                |
| K1 triple-tap | forward one sentence              |
| K2 tap        | back one sentence                 |
| K2 double-tap | slower (`-25` wpm)                |
| K2 hold       | save position & return to Library |

## Paused

Shown right after opening a book, or after pausing. The main screen
shows the current sentence with the current word highlighted; the side
screens brighten again and show progress (left) and key hints (right).

| Input         | Action                            |
|---------------|-----------------------------------|
| K1 tap        | resume playing                    |
| K1 double-tap | next chapter (if detected)        |
| K1 triple-tap | forward one sentence              |
| K2 tap        | back one sentence                 |
| K2 double-tap | previous chapter (if detected)    |
| K2 hold       | save position & return to Library |

Speed is adjusted while **Reading**, not here. Chapter skip only works
where a heading could be detected in the book (see below); otherwise
the double-taps do nothing.

## Confirm power-off

Reached via `K2 hold` from the Library.

| Input         | Action                               |
|---------------|--------------------------------------|
| K1 (any)      | power off (all screens go dark first)|
| anything else | cancel, return to Library            |

## End of book

Shown automatically after the last word. Any key returns to the Library.

## Speed limits

| Constant      | Value      |
|---------------|------------|
| `DEFAULT_WPM` | 250        |
| `MIN_WPM`     | 60         |
| `MAX_WPM`     | 900        |
| `WPM_STEP`    | 25 per tap |

## Chapter detection

When a book is opened its text is scanned for chapter/section headings
(`Chapter 12`, `Letter 1`, `XIV`, or a bare heading like `I. A SCANDAL
IN BOHEMIA`); for `.epub` files real HTML heading tags are used instead.
A bare roman numeral only counts when it stands alone, is punctuated
like a heading (`I.`) or is followed by an all-caps title, so "I went
home." is not mistaken for chapter I. This is a best-effort heuristic:
most Project Gutenberg books are detected reliably, unusual formatting
may yield few or no chapters.

## Fast reading (multi-word chunks)

If a frame ever takes longer to render and push than the word's delay
(the LCD itself refreshes in ~10 ms, so this only happens at extreme
wpm), several words are shown at once so the *average* pace still
matches. Each word keeps its own accent pivot letter as long as the
chunk fits on one line; otherwise it falls back to plain text rather
than cutting a word off.
