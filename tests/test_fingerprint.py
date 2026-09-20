"""Tests for the content-hash fingerprint system."""

import json
import os
import tempfile
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def test_compute_hash_deterministic():
    """Same inputs produce the same hash."""
    from fingerprint import compute_hash

    h1 = compute_hash("echo hello", "")
    h2 = compute_hash("echo hello", "")
    assert h1 == h2


def test_compute_hash_changes_with_recipe():
    """Different recipes produce different hashes."""
    from fingerprint import compute_hash

    h1 = compute_hash("echo hello", "")
    h2 = compute_hash("echo world", "")
    assert h1 != h2


def test_compute_hash_changes_with_deps():
    """Different dep content produces different hashes."""
    from fingerprint import compute_hash

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("print('hello')\n")
        dep1 = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("print('world')\n")
        dep2 = f.name

    try:
        h1 = compute_hash("python script", dep1)
        h2 = compute_hash("python script", dep2)
        assert h1 != h2
    finally:
        os.unlink(dep1)
        os.unlink(dep2)


def test_write_and_check_fingerprint():
    """Writing then checking a fingerprint works."""
    from fingerprint import write_fingerprint, check_fingerprint

    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "marker.done")
        recipe = "echo hello"
        deps = ""

        # No fingerprint yet — should not match.
        assert not check_fingerprint(target, recipe, deps)

        # Write fingerprint.
        write_fingerprint(target, recipe, deps)

        # Now it should match.
        assert check_fingerprint(target, recipe, deps)

        # Changed recipe — should not match.
        assert not check_fingerprint(target, "echo world", deps)


def test_fingerprint_cli_check():
    """The CLI --check exits 0 on match, 1 on mismatch."""
    import subprocess

    fp_script = str(Path(__file__).resolve().parent.parent / "lib" / "fingerprint.py")

    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "marker.done")

        # First check — no fingerprint, should exit 1.
        result = subprocess.run(
            [sys.executable, fp_script, "--check", "--target", target,
             "--recipe", "echo hello", "--deps", ""],
            capture_output=True,
        )
        assert result.returncode == 1

        # Write fingerprint.
        result = subprocess.run(
            [sys.executable, fp_script, "--write", "--target", target,
             "--recipe", "echo hello", "--deps", ""],
            capture_output=True,
        )
        assert result.returncode == 0

        # Second check — should match, exit 0.
        result = subprocess.run(
            [sys.executable, fp_script, "--check", "--target", target,
             "--recipe", "echo hello", "--deps", ""],
            capture_output=True,
        )
        assert result.returncode == 0
