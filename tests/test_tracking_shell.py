"""Tests for the vendored tracking_shell."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure lib is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "lib"))


def test_timing_record_format():
    """BEGIN/END records have the expected fields."""
    from tracking_shell import write_timing_record

    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "2026-09-08"))
        record = {
            "command": "echo hello",
            "target": "test_target",
            "unique_nr": 42,
            "has_make_level": True,
            "started_at": "2026-09-08T03:00:00.000000",
            "tag": "BEGIN",
        }
        write_timing_record(os.path.join(tmpdir, "2026-09-08"), record)
        path = os.path.join(tmpdir, "2026-09-08", "timing_env.log")
        assert os.path.exists(path)
        with open(path) as f:
            line = f.readline()
        parsed = json.loads(line)
        assert parsed["target"] == "test_target"
        assert parsed["tag"] == "BEGIN"
        assert parsed["unique_nr"] == 42


def test_tracking_shell_executes_command():
    """The tracking shell executes a command and returns the right exit code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        date = "2026-09-08"
        log_dir = os.path.join(tmpdir, "logs", date)
        os.makedirs(log_dir)

        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent.parent / "pipeline" / "lib" / "tracking_shell.py"),
                "--target", "test_target",
                "--date", date,
                "echo", "hello",
            ],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0
        # timing_env.log should have BEGIN and END records
        timing_path = os.path.join(log_dir, "timing_env.log")
        assert os.path.exists(timing_path)
        with open(timing_path) as f:
            lines = f.readlines()
        assert len(lines) == 2
        begin = json.loads(lines[0])
        end = json.loads(lines[1])
        assert begin["tag"] == "BEGIN"
        assert end["tag"] == "END"
        assert end["exit_code"] == 0

        # Target log should exist
        target_log = os.path.join(log_dir, "test_target.log")
        assert os.path.exists(target_log)


def test_tracking_shell_preserves_exit_code():
    """Non-zero exit codes are preserved through the tracking shell."""
    with tempfile.TemporaryDirectory() as tmpdir:
        date = "2026-09-08"
        log_dir = os.path.join(tmpdir, "logs", date)
        os.makedirs(log_dir)

        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent.parent / "pipeline" / "lib" / "tracking_shell.py"),
                "--target", "failing_target",
                "--date", date,
                "false",  # always exits 1
            ],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 1
        timing_path = os.path.join(log_dir, "timing_env.log")
        with open(timing_path) as f:
            lines = f.readlines()
        end = json.loads(lines[1])
        assert end["exit_code"] == 1
