"""Unit tests for the stress test engine (rapid_reader/stress.py)."""

import os
import queue

import pytest

import books
import config
import main
import stress


class _NullInput:
    def __init__(self, on_event):
        self.keys = {}


@pytest.fixture
def app(fake_display, monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)

    def make(**kwargs):
        return main.App(display=fake_display, input_cls=_NullInput, **kwargs)

    return make


def _write_book(name, text):
    p = os.path.join(config.BOOKS_DIR, name)
    with open(p, "w") as f:
        f.write(text)
    return p


# ---- read_temp_c -------------------------------------------------------

def test_read_temp_c_missing_path_returns_none(tmp_path):
    assert stress.read_temp_c(path=str(tmp_path / "missing")) is None


def test_read_temp_c_parses_millidegrees(tmp_path):
    p = tmp_path / "temp"
    p.write_text("45123\n")
    assert stress.read_temp_c(path=str(p)) == pytest.approx(45.123)


# ---- read_throttled -----------------------------------------------------

def test_read_throttled_missing_binary_returns_none(monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError("no vcgencmd")
    monkeypatch.setattr(stress.subprocess, "run", fake_run)
    assert stress.read_throttled() is None


def test_read_throttled_parses_bitmask(monkeypatch):
    class Result:
        stdout = "throttled=0x50005\n"

    monkeypatch.setattr(stress.subprocess, "run", lambda *a, **k: Result())
    flags = stress.read_throttled()
    assert flags["under_voltage_now"] is True
    assert flags["throttled_now"] is True
    assert flags["freq_capped_now"] is False
    assert flags["under_voltage_since_boot"] is True
    assert flags["throttled_since_boot"] is True


# ---- cpu_bench -----------------------------------------------------------

def test_cpu_bench_runs_for_roughly_the_requested_duration():
    result = stress.cpu_bench(0.05)
    assert result["ops"] > 0
    assert result["ops_per_sec"] > 0
    assert result["elapsed"] >= 0.05


def test_cpu_bench_should_abort_stops_immediately():
    result = stress.cpu_bench(60, should_abort=lambda: True)
    # One batch runs before the abort check; well under the full duration.
    assert result["elapsed"] < 5.0


def test_cpu_bench_reports_progress(monkeypatch):
    fractions = []
    stress.cpu_bench(0.02, on_tick=fractions.append)
    assert fractions
    assert all(0.0 <= f <= 1.0 for f in fractions)


# ---- simulate_activity ----------------------------------------------------

def test_simulate_activity_falls_back_without_a_library(app):
    a = app()
    counts = stress.simulate_activity(a, 0.3)
    assert counts["loads"] >= 1
    assert counts["words"] > 0
    assert counts["list_frames"] > 0
    assert counts["paused_frames"] > 0


def test_simulate_activity_uses_real_book_when_present(app):
    _write_book("sample.txt", "One two three. Four five six seven eight nine.")
    a = app()
    counts = stress.simulate_activity(a, 0.05)
    assert counts["loads"] >= 1
    assert counts["words"] > 0


def test_simulate_activity_stops_on_abort(app):
    a = app()
    aborted = [False]
    calls = []

    def should_abort():
        calls.append(1)
        if len(calls) > 1:
            aborted[0] = True
        return aborted[0]

    counts = stress.simulate_activity(a, 60, should_abort=should_abort)
    assert counts["words"] < 10000  # stopped early, not a full 60s run


def test_simulate_activity_cleans_up_fallback_temp_file(app, monkeypatch):
    created = []
    real_load = books.Book.load

    def spy_load(path):
        created.append(path)
        return real_load(path)

    monkeypatch.setattr(books.Book, "load", spy_load)
    a = app()
    stress.simulate_activity(a, 0.02)
    for path in created:
        assert not os.path.exists(path)


# ---- run() orchestration -------------------------------------------------

def test_run_both_writes_log_and_returns_summary(app, tmp_path):
    a = app()
    log_path = str(tmp_path / "stress" / "run.log")
    result = stress.run(a, log_path, "both", phase_secs=0.1)

    assert os.path.exists(log_path)
    content = open(log_path).read()
    assert "mode: both" in content
    assert "CPU bench" in content
    assert "Activity simulation" in content
    assert "Samples" in content

    for key in ("mode", "aborted", "elapsed", "cpu_ops_per_sec", "words_per_sec",
                "list_frames_per_sec", "paused_frames_per_sec",
                "temp_start", "temp_end", "temp_min", "temp_max", "temp_avg",
                "throttled", "log_path"):
        assert key in result
    assert result["mode"] == "both"
    assert result["aborted"] is False
    assert result["cpu_ops_per_sec"] is not None
    assert result["words_per_sec"] is not None
    assert result["log_path"] == log_path


def test_run_cpu_only_omits_activity(app, tmp_path):
    a = app()
    log_path = str(tmp_path / "stress" / "cpu.log")
    result = stress.run(a, log_path, "cpu", phase_secs=0.05)

    content = open(log_path).read()
    assert "mode: cpu" in content
    assert "CPU bench" in content
    assert "Activity simulation" not in content

    assert result["mode"] == "cpu"
    assert result["cpu_ops_per_sec"] is not None
    assert result["words_per_sec"] is None
    assert result["list_frames_per_sec"] is None
    assert result["paused_frames_per_sec"] is None


def test_run_rsvp_only_omits_cpu(app, tmp_path):
    a = app()
    log_path = str(tmp_path / "stress" / "rsvp.log")
    result = stress.run(a, log_path, "rsvp", phase_secs=0.05)

    content = open(log_path).read()
    assert "mode: rsvp" in content
    assert "Activity simulation" in content
    assert "CPU bench" not in content

    assert result["mode"] == "rsvp"
    assert result["cpu_ops_per_sec"] is None
    assert result["words_per_sec"] is not None
    assert result["list_frames_per_sec"] is not None
    assert result["paused_frames_per_sec"] is not None


def test_run_marks_aborted_when_should_abort_fires_immediately(app, tmp_path):
    a = app()
    log_path = str(tmp_path / "stress" / "run.log")
    result = stress.run(a, log_path, "both", phase_secs=60,
                        should_abort=lambda: True)
    assert result["aborted"] is True
    assert result["elapsed"] < 5.0
    # Aborted during CPU, so activity never ran.
    assert result["cpu_ops_per_sec"] is not None
    assert result["words_per_sec"] is None


def test_run_rejects_unknown_mode(app, tmp_path):
    a = app()
    with pytest.raises(ValueError, match="unknown stress mode"):
        stress.run(a, str(tmp_path / "x.log"), "nope", phase_secs=0.01)