"""Tests for the Slack notification builder."""

import json
import os
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def test_build_failure_ping():
    """Failure ping contains date and exit code."""
    from notify_slack import build_failure_ping

    with tempfile.TemporaryDirectory() as tmpdir:
        date_dir = os.path.join(tmpdir, "2026-09-08")
        os.makedirs(date_dir)
        timing_path = os.path.join(date_dir, "timing_env.log")

        with open(timing_path, "w") as f:
            f.write(json.dumps({
                "command": "false", "target": "bad_target", "unique_nr": 0,
                "has_make_level": True, "started_at": "2026-09-08T03:00:00.000000",
                "tag": "BEGIN",
            }) + "\n")
            f.write(json.dumps({
                "command": "false", "target": "bad_target", "unique_nr": 0,
                "has_make_level": True, "started_at": "2026-09-08T03:00:00.000000",
                "finished_at": "2026-09-08T03:00:01.000000", "exit_code": 1,
                "tag": "END",
            }) + "\n")

        payload = build_failure_ping("2026-09-08", 1, tmpdir)
        assert "FAILED" in payload["text"]
        assert "2026-09-08" in payload["text"]
        assert "bad_target" in payload["text"]


def test_build_morning_digest():
    """Morning digest contains summary and per-target info."""
    from notify_slack import build_morning_digest

    with tempfile.TemporaryDirectory() as tmpdir:
        date_dir = os.path.join(tmpdir, "2026-09-08")
        os.makedirs(date_dir)
        timing_path = os.path.join(date_dir, "timing_env.log")

        with open(timing_path, "w") as f:
            f.write(json.dumps({
                "command": "echo ok", "target": "good_target", "unique_nr": 0,
                "has_make_level": True, "started_at": "2026-09-08T03:00:00.000000",
                "tag": "BEGIN",
            }) + "\n")
            f.write(json.dumps({
                "command": "echo ok", "target": "good_target", "unique_nr": 0,
                "has_make_level": True, "started_at": "2026-09-08T03:00:00.000000",
                "finished_at": "2026-09-08T03:00:05.000000", "exit_code": 0,
                "tag": "END",
            }) + "\n")

        payload = build_morning_digest("2026-09-08", tmpdir)
        full_text = payload["blocks"][0]["text"]["text"]
        assert "digest" in payload["text"]
        assert "good_target" in full_text


def test_send_slack_success():
    """send_slack returns True on HTTP 200."""
    from notify_slack import send_slack

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = send_slack("https://hooks.slack.com/test", {"text": "test"})
        assert result is True


def test_send_slack_failure():
    """send_slack returns False on exception."""
    from notify_slack import send_slack

    with patch("urllib.request.urlopen", side_effect=Exception("network error")):
        result = send_slack("https://hooks.slack.com/test", {"text": "test"})
        assert result is False
