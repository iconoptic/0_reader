"""Stress test engine: a generic CPU benchmark and/or a simulated
sequence of real reading-app activity, both run at maximum speed to help
compare thermal hardware (e.g. two candidate heatsinks) on the Pi Zero W.

Modes (each phase lasts ~Ts = config.STRESS_TS_SECS):
  rsvp — activity simulation only
  cpu  — SHA256 bench only
  both — CPU then activity (~2Ts)

No hardware-only imports at module load (mirrors buttons.py/oled.py): this
runs and is fully unit-testable on a dev box with no thermal sysfs and no
vcgencmd.
"""

import hashlib
import os
import subprocess
import tempfile
import time

import books
import config
import render

_SAMPLE_BATCH = 2000

_FALLBACK_TEXT = """\
Rapid Reader Stress Test Sample. The quick brown fox jumps over the lazy
dog, again and again, until the sentence loses all its meaning and
becomes nothing more than a sequence of shapes flashed on a small screen.
Optimal recognition points, extraordinarily long compound words, short
ones, and punctuated clauses; all of it exercises the same rendering
pipeline a real book would.

This second paragraph exists mainly so a paragraph boundary and a second
chapter-shaped block of text are both present, since the tokenizer treats
paragraph ends specially and a stress test should exercise that path too,
not just a single uninterrupted run of words. Supercalifragilisticexpialidocious
words like that one also force the two-line word-wrap fallback to run at
least once per pass through this sample.
"""


_THERMAL_ZONE_PATH = "/sys/class/thermal/thermal_zone0/temp"


def read_temp_c(path=_THERMAL_ZONE_PATH):
    """Current CPU/SoC temperature in Celsius, or None off-Pi/on error."""
    try:
        with open(path) as f:
            raw = f.read().strip()
        return int(raw) / 1000.0
    except (OSError, ValueError):
        return None


_THROTTLE_BITS = (
    (0, "under_voltage_now"),
    (1, "freq_capped_now"),
    (2, "throttled_now"),
    (16, "under_voltage_since_boot"),
    (17, "freq_capped_since_boot"),
    (18, "throttled_since_boot"),
)


def read_throttled():
    """Parse `vcgencmd get_throttled`'s bitmask into named flags, or None
    if vcgencmd isn't present/usable (any non-Pi dev box)."""
    try:
        out = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True,
            text=True, timeout=2.0, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        mask = int(out.strip().split("=", 1)[1], 0)
    except (IndexError, ValueError):
        return None
    return {name: bool(mask & (1 << bit)) for bit, name in _THROTTLE_BITS}


def cpu_bench(duration, on_tick=None, should_abort=None):
    """Generic stdlib-only CPU-bound load: chained sha256 for `duration`
    seconds. Returns {"ops", "elapsed", "ops_per_sec"}."""
    start = time.monotonic()
    ops = 0
    data = os.urandom(64)
    while True:
        for _ in range(_SAMPLE_BATCH):
            data = hashlib.sha256(data).digest()
        ops += _SAMPLE_BATCH
        elapsed = time.monotonic() - start
        fraction = min(1.0, elapsed / duration) if duration > 0 else 1.0
        if on_tick:
            on_tick(fraction)
        if elapsed >= duration or (should_abort and should_abort()):
            break
    elapsed = time.monotonic() - start
    return {"ops": ops, "elapsed": elapsed,
            "ops_per_sec": ops / elapsed if elapsed > 0 else 0.0}


def _pick_book_path():
    """Return (path, is_temp): the largest bundled book, or a fallback
    sample written to a temp file when the library is empty."""
    library = books.scan_library()
    if library:
        return max(library, key=lambda item: os.path.getsize(item[1]))[1], False
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="stress-sample-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_FALLBACK_TEXT)
    return path, True


def simulate_activity(app, duration, on_tick=None, should_abort=None):
    """Drive the real rendering pipeline (word/list/paused frames) at
    maximum speed, uncapped by any WPM delay, cycling through book
    load+tokenize, RSVP flashing, list scrolling, and paused/sentence
    rendering until `duration` elapses. Returns per-activity counters."""
    start = time.monotonic()
    counts = {"loads": 0, "words": 0, "list_frames": 0, "paused_frames": 0}
    scroll_rows = ["Item %d" % i for i in range(200)]
    path, is_temp = _pick_book_path()

    def elapsed():
        return time.monotonic() - start

    def done():
        return elapsed() >= duration or (should_abort and should_abort())

    def _tick():
        if on_tick:
            on_tick(min(1.0, elapsed() / duration) if duration > 0 else 1.0)

    try:
        while not done():
            book = books.Book.load(path)
            counts["loads"] += 1
            _tick()

            for i, word in enumerate(book.words):
                img = render.word_frame(word, app.theme,
                                         word_size=app.state.settings["word_size"])
                app.display.show(img)
                counts["words"] += 1
                if i % 10 == 0:
                    _tick()
                    if done():
                        return counts

            for top in range(0, len(scroll_rows) - 4):
                img = render.list_frame("STRESS", scroll_rows, top, top, rows_visible=4)
                app.display.show(img)
                counts["list_frames"] += 1
                if top % 10 == 0:
                    _tick()
                    if done():
                        return counts

            for i, sentence_start in enumerate(book.sentence_starts):
                idx = sentence_start
                progress = min(1.0, idx / max(1, len(book.words)))
                img = render.paused_frame(book.title, book.words, idx, sentence_start,
                                           config.MAX_WPM, progress, app.theme)
                app.display.show(img)
                counts["paused_frames"] += 1
                if i % 5 == 0:
                    _tick()
                    if done():
                        return counts
    finally:
        if is_temp:
            try:
                os.remove(path)
            except OSError:
                pass

    return counts


def _write_log(log_path, mode, phase_secs, cpu_result, activity_result,
               samples, aborted):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("Rapid Reader stress test log\n")
        f.write("mode: %s\n" % mode)
        f.write("phase_secs: %s\n" % phase_secs)
        f.write("started: %s\n" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        f.write("aborted: %s\n\n" % aborted)
        if cpu_result is not None:
            f.write("== CPU bench ==\n")
            for k, v in cpu_result.items():
                f.write("%s: %s\n" % (k, v))
            f.write("\n")
        if activity_result is not None:
            f.write("== Activity simulation ==\n")
            for k, v in activity_result.items():
                f.write("%s: %s\n" % (k, v))
            f.write("\n")
        f.write("== Samples (elapsed_s, temp_c, throttled) ==\n")
        for elapsed, temp, throttled in samples:
            f.write("%.1f, %s, %s\n" % (
                elapsed, "%.1f" % temp if temp is not None else "n/a", throttled))


def run(app, log_path, mode, phase_secs=None, on_progress=None, should_abort=None):
    """Run a stress test mode: "rsvp" (activity only), "cpu" (bench only),
    or "both" (CPU then activity). Each included phase runs for
    `phase_secs` (defaults to config.STRESS_TS_SECS), so "both" lasts ~2Ts.
    Samples temperature/throttle state at config.STRESS_SAMPLE_SECS
    cadence throughout, writes the full detail to `log_path`, and returns
    a summary dict for the results screen. Skipped-phase metrics are None."""
    if phase_secs is None:
        phase_secs = config.STRESS_TS_SECS
    if mode not in ("rsvp", "cpu", "both"):
        raise ValueError("unknown stress mode: %r" % (mode,))

    samples = []
    last_sample_at = [0.0]
    last_temp = [None]
    run_start = time.monotonic()

    def _sample_if_due(phase, phase_fraction):
        now = time.monotonic() - run_start
        if now - last_sample_at[0] >= config.STRESS_SAMPLE_SECS or not samples:
            last_sample_at[0] = now
            last_temp[0] = read_temp_c()
            throttled = read_throttled()
            flag = (throttled or {}).get("throttled_now", False)
            samples.append((now, last_temp[0], flag))
        if on_progress:
            temp = last_temp[0]
            label = "%s  %s" % (phase, "%.0fC" % temp if temp is not None else "")
            on_progress(phase.lower().replace(" ", "_"), phase_fraction, label.strip())

    aborted = False
    cpu_result = None
    activity_result = None

    if mode in ("cpu", "both"):
        cpu_result = cpu_bench(
            phase_secs, on_tick=lambda f: _sample_if_due("CPU bench", f),
            should_abort=should_abort)
        if should_abort and should_abort():
            aborted = True

    if mode in ("rsvp", "both") and not aborted:
        activity_result = simulate_activity(
            app, phase_secs, on_tick=lambda f: _sample_if_due("Activity sim", f),
            should_abort=should_abort)
        if should_abort and should_abort():
            aborted = True

    throttled_final = read_throttled()
    temps = [t for _, t, _ in samples if t is not None]
    _write_log(log_path, mode, phase_secs, cpu_result, activity_result,
               samples, aborted)

    words_per_sec = None
    list_frames_per_sec = None
    paused_frames_per_sec = None
    if activity_result is not None and phase_secs > 0:
        words_per_sec = activity_result["words"] / phase_secs
        list_frames_per_sec = activity_result["list_frames"] / phase_secs
        paused_frames_per_sec = activity_result["paused_frames"] / phase_secs

    return {
        "mode": mode,
        "aborted": aborted,
        "elapsed": time.monotonic() - run_start,
        "cpu_ops_per_sec": (cpu_result["ops_per_sec"]
                            if cpu_result is not None else None),
        "words_per_sec": words_per_sec,
        "list_frames_per_sec": list_frames_per_sec,
        "paused_frames_per_sec": paused_frames_per_sec,
        "temp_start": temps[0] if temps else None,
        "temp_end": temps[-1] if temps else None,
        "temp_min": min(temps) if temps else None,
        "temp_max": max(temps) if temps else None,
        "temp_avg": sum(temps) / len(temps) if temps else None,
        "throttled": throttled_final,
        "log_path": log_path,
    }
