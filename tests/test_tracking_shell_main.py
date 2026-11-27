"""Tests that call tracking_shell.main() directly.

The existing test_tracking_shell.py runs the script as a subprocess, so its
coverage of main() doesn't count.  Here we monkeypatch sys.argv and
subprocess.run and call main() in-process, exercising the argv parsing,
BEGIN/END record writing, target-log creation, and exit-code preservation.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "lib"))

import tracking_shell  # noqa: E402


def _read_timing(log_dir):
    path = os.path.join(log_dir, "timing_env.log")
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def test_main_writes_begin_end_records(monkeypatch, tmp_path):
    """main() writes a BEGIN then an END record to timing_env.log."""
    date = "2026-09-08"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["tracking_shell.py", "--target", "build", "--date", date, "-c", "echo hi"],
    )
    fake = mock.MagicMock()
    fake.returncode = 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)

    with pytest.raises(SystemExit) as exc:
        tracking_shell.main()
    assert exc.value.code == 0

    log_dir = os.path.join("logs", date)
    records = _read_timing(log_dir)
    assert len(records) == 2
    assert records[0]["tag"] == "BEGIN"
    assert records[1]["tag"] == "END"
    assert records[0]["target"] == "build"
    assert records[1]["target"] == "build"
    assert records[0]["unique_nr"] == records[1]["unique_nr"]
    # BEGIN carries started_at; END carries started_at + finished_at + exit_code.
    assert "started_at" in records[0]
    assert "finished_at" in records[1]
    assert records[1]["exit_code"] == 0
    assert records[0]["command"] == "echo hi"


def test_main_creates_target_log(monkeypatch, tmp_path):
    """main() creates the per-target log file with a header."""
    date = "2026-09-08"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["tracking_shell.py", "--target", "build", "--date", date, "-c", "echo hi"],
    )
    fake = mock.MagicMock()
    fake.returncode = 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)

    with pytest.raises(SystemExit):
        tracking_shell.main()

    target_log = os.path.join("logs", date, "build.log")
    assert os.path.exists(target_log)
    with open(target_log) as f:
        content = f.read()
    assert "Working on target build" in content
    assert "attempt" in content


def test_main_preserves_nonzero_exit_code(monkeypatch, tmp_path):
    """A non-zero exit code from the wrapped command is preserved."""
    date = "2026-09-08"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["tracking_shell.py", "--target", "fail", "--date", date, "-c", "false"],
    )
    fake = mock.MagicMock()
    fake.returncode = 42
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)

    with pytest.raises(SystemExit) as exc:
        tracking_shell.main()
    assert exc.value.code == 42

    records = _read_timing(os.path.join("logs", date))
    assert records[1]["exit_code"] == 42


def test_main_no_target_when_at_does_not_expand(monkeypatch, tmp_path):
    """When $@ doesn't expand (make 3.81), --target is followed by another
    flag, so the target defaults to 'no-target'."""
    date = "2026-09-08"
    monkeypatch.chdir(tmp_path)
    # --target immediately followed by --date (the next token starts with '-').
    monkeypatch.setattr(
        sys, "argv",
        ["tracking_shell.py", "--target", "--date", date, "-c", "echo hi"],
    )
    fake = mock.MagicMock()
    fake.returncode = 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)

    with pytest.raises(SystemExit):
        tracking_shell.main()

    records = _read_timing(os.path.join("logs", date))
    assert records[0]["target"] == "no-target"
    assert records[1]["target"] == "no-target"
    # The no-target log file uses an underscore-safe name.
    assert os.path.exists(os.path.join("logs", date, "no-target.log"))


def test_main_no_command_exits_zero_without_writing(monkeypatch, tmp_path):
    """With no -c and no rest args, main() exits 0 and writes nothing."""
    date = "2026-09-08"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["tracking_shell.py", "--target", "build", "--date", date],
    )
    run_called = []
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: run_called.append(1) or mock.MagicMock(returncode=0)
    )

    with pytest.raises(SystemExit) as exc:
        tracking_shell.main()
    assert exc.value.code == 0
    # No logs directory was created because the command was empty.
    assert not os.path.exists(os.path.join("logs", date))
    assert run_called == []


def test_main_defaults_date_to_today(monkeypatch, tmp_path):
    """When --date is omitted, today's date is used for the log directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["tracking_shell.py", "--target", "build", "-c", "echo hi"],
    )
    fake = mock.MagicMock()
    fake.returncode = 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)

    expected_date = tracking_shell.today_str()
    with pytest.raises(SystemExit):
        tracking_shell.main()

    assert os.path.exists(os.path.join("logs", expected_date, "timing_env.log"))


def test_main_slash_target_sanitized_in_log_name(monkeypatch, tmp_path):
    """A target containing '/' is sanitized to '_' in the log filename."""
    date = "2026-09-08"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["tracking_shell.py", "--target", "dir/sub", "--date", date, "-c", "echo hi"],
    )
    fake = mock.MagicMock()
    fake.returncode = 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)

    with pytest.raises(SystemExit):
        tracking_shell.main()

    assert os.path.exists(os.path.join("logs", date, "dir_sub.log"))
