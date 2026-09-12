"""Exercise system/rapid-reader-ota-apply as a script, against a temp
tree instead of the live device paths (docs/plan_1/phase-1-recovery.md
deliverable 4; extended by docs/plan_1/phase-4-atomic-apply.md).

Covers: splash/ and ownership survive an apply; a wrong-size splash.bin
or an unverifiable staged tree makes the helper refuse rather than
restart into a broken tree; the atomic .new/.prev swap leaves the live
tree untouched on any before-commit failure and keeps one rollback
generation on success.
"""

import hashlib
import os
import subprocess

import pytest

HELPER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "system", "rapid-reader-ota-apply")

# Mirrors the helper's own REQUIRED_FILES — the card-build smoke test's
# import list plus boot.py.
REQUIRED_FILES = ["boot.py", "config.py", "oled.py", "display.py",
                  "render.py", "rsvp.py", "books.py", "theme.py", "main.py"]


def _run(env, *args):
    full_env = dict(os.environ)
    full_env.update(env)
    full_env["OTA_APPLY_TEST_MODE"] = "1"  # skip chown-to-root/systemctl
    return subprocess.run(
        ["bash", HELPER, *args], env=full_env,
        capture_output=True, text=True)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_incoming(ota_dir, omit=()):
    """A staged tree with every required module present (content
    distinguishable per file) plus main.py, shaped like what
    sync_to_pi.sh actually ships. `omit` drops named files, to test a
    staged tree that is missing something the manifest never claimed."""
    incoming = ota_dir / "incoming"
    incoming.mkdir(parents=True)
    for name in REQUIRED_FILES:
        if name in omit:
            continue
        text = "new\n" if name == "main.py" else "content of %s\n" % name
        (incoming / name).write_text(text)
    return incoming


def _write_manifest(incoming, manifest_path):
    """sha256sum-compatible manifest of whatever currently exists under
    incoming/ — i.e. a manifest that matches the staged tree as of the
    moment it's written, the same as a real host sync producing one
    right after its rsync completes."""
    lines = [
        "%s  %s\n" % (_sha256(p), p.relative_to(incoming))
        for p in sorted(incoming.rglob("*")) if p.is_file()
    ]
    manifest_path.write_text("".join(lines))


def _make_dest(root, splash_bytes=1024):
    """A DEST tree shaped like a real /opt/rapid-reader: app files plus
    a splash/ the staged incoming/ tree never carries."""
    dest = root / "dest"
    (dest / "splash").mkdir(parents=True)
    (dest / "splash" / "splash.bin").write_bytes(b"\x00" * splash_bytes)
    for name in REQUIRED_FILES:
        (dest / name).write_text("old content\n")
    return dest


@pytest.fixture
def ota_env(tmp_path):
    ota_dir = tmp_path / "ota"
    incoming = _make_incoming(ota_dir)
    manifest = ota_dir / "manifest"
    _write_manifest(incoming, manifest)
    dest = _make_dest(tmp_path)
    pending = ota_dir / "pending"
    failed = ota_dir / "failed"
    progress = ota_dir / "progress"
    new = tmp_path / "dest.new"
    prev = tmp_path / "dest.prev"
    return {
        "ota_dir": ota_dir, "incoming": incoming, "manifest": manifest,
        "pending": pending, "failed": failed, "progress": progress,
        "dest": dest, "new": new, "prev": prev,
        "env": {
            "OTA_DIR": str(ota_dir),
            "OTA_INCOMING": str(incoming),
            "OTA_PENDING": str(pending),
            "OTA_FAILED": str(failed),
            "OTA_PROGRESS": str(progress),
            "OTA_MANIFEST": str(manifest),
            "OTA_DEST": str(dest),
            "OTA_DEST_NEW": str(new),
            "OTA_DEST_PREV": str(prev),
        },
    }


def test_apply_preserves_splash_and_installs_new_files(ota_env):
    ota_env["pending"].write_text("now\n")

    result = _run(ota_env["env"])

    assert result.returncode == 0, result.stderr
    assert (ota_env["dest"] / "main.py").read_text() == "new\n"
    splash = ota_env["dest"] / "splash" / "splash.bin"
    assert splash.exists()
    assert len(splash.read_bytes()) == 1024
    assert not ota_env["pending"].exists()
    assert not ota_env["failed"].exists()
    assert not ota_env["progress"].exists()
    assert not ota_env["manifest"].exists()
    # incoming/ is cleared and recreated for the next stage.
    assert ota_env["incoming"].is_dir()
    assert list(ota_env["incoming"].iterdir()) == []


def test_apply_keeps_one_rollback_generation(ota_env):
    result = _run(ota_env["env"])

    assert result.returncode == 0, result.stderr
    # .prev is the tree that was live before this apply — the rollback
    # phase 4 exists to provide, absent in the pre-phase-4 design.
    assert (ota_env["prev"] / "main.py").read_text() == "old content\n"
    assert (ota_env["prev"] / "splash" / "splash.bin").exists()
    assert not ota_env["new"].exists()  # renamed into place, not left behind


def test_apply_refuses_manifest_mismatch_and_leaves_dest_untouched(ota_env):
    # Simulate exactly what an interrupted host->incoming transfer over
    # wifi leaves behind: a file whose content no longer matches what
    # the manifest (written right after a *complete* transfer) recorded.
    (ota_env["incoming"] / "main.py").write_text("tru")  # truncated

    result = _run(ota_env["env"])

    assert result.returncode != 0
    assert "manifest" in result.stderr
    # Verification happens before anything under DEST is touched.
    assert (ota_env["dest"] / "main.py").read_text() == "old content\n"
    assert not ota_env["new"].exists()
    assert not ota_env["prev"].exists()


def test_apply_refuses_when_manifest_lists_a_now_missing_file(ota_env):
    # The manifest was written when the file existed; it vanished after
    # (e.g. the sync was killed between staging and this apply running).
    (ota_env["incoming"] / "render.py").unlink()

    result = _run(ota_env["env"])

    assert result.returncode != 0
    assert "manifest" in result.stderr
    assert (ota_env["dest"] / "main.py").read_text() == "old content\n"


def test_apply_refuses_missing_manifest(ota_env):
    ota_env["manifest"].unlink()

    result = _run(ota_env["env"])

    assert result.returncode != 0
    assert "manifest" in result.stderr
    assert (ota_env["dest"] / "main.py").read_text() == "old content\n"


def test_apply_refuses_staged_tree_missing_a_required_module(ota_env):
    # A file the manifest never mentions and was never staged at all —
    # distinct from a manifest *mismatch*: the transfer completed
    # exactly as recorded, but what got staged still isn't a runnable
    # app (docs/plan_1/phase-0-ota-contracts.md §3).
    incoming = ota_env["ota_dir"] / "incoming"
    (incoming / "render.py").unlink()
    _write_manifest(incoming, ota_env["manifest"])

    result = _run(ota_env["env"])

    assert result.returncode != 0
    assert "render.py" in result.stderr
    assert (ota_env["dest"] / "main.py").read_text() == "old content\n"


def test_apply_refuses_wrong_size_splash(ota_env):
    # Corrupt the live splash the way a partial write or a pre-OTA-splash
    # card might: present, but not the size build_card.sh guarantees.
    (ota_env["dest"] / "splash" / "splash.bin").write_bytes(b"\x00" * 3)

    result = _run(ota_env["env"])

    assert result.returncode != 0
    assert "splash" in result.stderr
    # The bad splash is only ever copied into the side-by-side .new tree
    # (phase 4's atomic swap) — the live tree is never touched or swapped.
    # .new itself is left behind for diagnosis, same as incoming/ is.
    assert (ota_env["dest"] / "main.py").read_text() == "old content\n"
    assert not ota_env["prev"].exists()


def test_apply_refuses_missing_splash(ota_env):
    (ota_env["dest"] / "splash" / "splash.bin").unlink()

    result = _run(ota_env["env"])

    assert result.returncode != 0
    assert "splash" in result.stderr


def test_apply_refuses_missing_incoming(ota_env):
    import shutil
    shutil.rmtree(ota_env["incoming"])

    result = _run(ota_env["env"])

    assert result.returncode != 0
    assert "missing" in result.stderr


# --- --check preflight mode (docs/plan_1/phase-3-bootstrap.md) --------
#
# tools/sync_to_pi.sh runs `sudo -n <helper> --check` to prove the sudoers
# rule is in effect before it stages or arms anything. If --check could
# apply, that probe would silently install a stale staged tree on every
# sync, so "never applies" is the invariant worth pinning down.

def test_check_reports_ready_without_applying(ota_env):
    ota_env["pending"].write_text("now\n")

    result = _run(ota_env["env"], "--check")

    assert result.returncode == 0, result.stderr
    assert "ready" in result.stdout
    assert "staged tree present" in result.stdout
    # Nothing moved: dest untouched, staging intact, trigger still armed.
    assert (ota_env["dest"] / "main.py").read_text() == "old content\n"
    assert (ota_env["incoming"] / "main.py").exists()
    assert ota_env["pending"].exists()


def test_check_reports_not_staged_on_empty_incoming(ota_env):
    import shutil
    shutil.rmtree(ota_env["incoming"])
    ota_env["incoming"].mkdir()

    result = _run(ota_env["env"], "--check")

    assert result.returncode == 0, result.stderr
    assert "not staged" in result.stdout


def test_check_fails_when_dest_missing(ota_env):
    import shutil
    shutil.rmtree(ota_env["dest"])

    result = _run(ota_env["env"], "--check")

    assert result.returncode != 0
    assert "missing" in result.stderr


def test_unknown_argument_refuses_and_does_not_apply(ota_env):
    result = _run(ota_env["env"], "--aply")   # a plausible typo

    assert result.returncode == 2
    assert "unknown argument" in result.stderr
    assert (ota_env["dest"] / "main.py").read_text() == "old content\n"
