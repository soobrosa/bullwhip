#!/usr/bin/env python3
"""notify_slack.py — Slack notification for bullwhip.

v0: failure ping on final attempt (stdlib urllib, zero deps).
v1: morning digest with per-target duration vs. historical average.

Config: SLACK_WEBHOOK_URL in config/bullwhip.sh (same export KEY=VAL convention).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# Allow importing the reducer logic from the same parsers.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def parse_timing_log(log_dir: str, date: str) -> list[dict]:
    """Parse timing_env.log for a given date, return list of target dicts."""
    path = os.path.join(log_dir, date, "timing_env.log")
    if not os.path.exists(path):
        return []

    begin_records: dict[int, dict] = {}
    results: list[dict] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = rec.get("unique_nr")
            if key is None:
                continue
            if rec.get("tag") == "BEGIN":
                begin_records[key] = rec
            elif rec.get("tag") == "END" and key in begin_records:
                begin = begin_records.pop(key)
                try:
                    start = datetime.fromisoformat(begin["started_at"])
                    end = datetime.fromisoformat(rec["finished_at"])
                    duration = (end - start).total_seconds()
                    results.append({
                        "target": rec.get("target", ""),
                        "duration": duration,
                        "exit_code": rec.get("exit_code", -1),
                        "started_at": begin["started_at"],
                    })
                except (KeyError, ValueError):
                    pass

    return results


def get_historical_averages(log_dir: str, date: str, days: int = 7) -> dict[str, float]:
    """Get average duration per target over the last N days."""
    from collections import defaultdict

    target_durations: dict[str, list[float]] = defaultdict(list)

    # Parse dates from the logs directory.
    if not os.path.isdir(log_dir):
        return {}

    for date_dir in sorted(os.listdir(log_dir)):
        timing_path = os.path.join(log_dir, date_dir, "timing_env.log")
        if not os.path.exists(timing_path):
            continue
        for rec in parse_timing_log(log_dir, date_dir):
            if rec["exit_code"] == 0:
                target_durations[rec["target"]].append(rec["duration"])

    return {
        t: sum(durs) / len(durs)
        for t, durs in target_durations.items()
        if durs
    }


def send_slack(webhook_url: str, payload: dict) -> bool:
    """Send a Slack webhook payload. Returns True on success."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[notify_slack] Failed to send: {e}", file=sys.stderr)
        return False


def build_failure_ping(date: str, exit_code: int, log_dir: str) -> dict:
    """v0: failure ping — plain text, minimal blocks."""
    targets = parse_timing_log(log_dir, date)
    failed = [t for t in targets if t["exit_code"] != 0]

    text = f":rotating_light: *bullwhip FAILED on {date}*\n"
    text += f"Exit code: {exit_code}\n"
    text += f"Failed targets: {len(failed)}\n"
    for t in failed[:10]:
        text += f"  • `{t['target']}` (exit {t['exit_code']}, {t['duration']:.1f}s)\n"

    return {
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ],
    }


def build_morning_digest(date: str, log_dir: str) -> dict:
    """v1: morning digest with per-target duration vs. historical average."""
    targets = parse_timing_log(log_dir, date)
    averages = get_historical_averages(log_dir, date)

    succeeded = [t for t in targets if t["exit_code"] == 0]
    failed = [t for t in targets if t["exit_code"] != 0]
    total_runtime = sum(t["duration"] for t in targets)

    headline = (
        f":sunrise: *bullwhip digest for {date}*\n"
        f"{'✅ All succeeded' if not failed else f'❌ {len(failed)} failed'} "
        f"— {len(succeeded)} succeeded — total runtime {total_runtime:.0f}s"
    )

    # Per-target table with anomaly detection.
    lines = []
    for t in sorted(targets, key=lambda x: -x["duration"]):
        avg = averages.get(t["target"], 0)
        anomaly = ""
        if avg > 0 and t["duration"] > avg * 1.5:
            anomaly = " ⚠️ slow"
        elif avg > 0 and t["duration"] < avg * 0.5:
            anomaly = " ⚡ fast"
        status = "✅" if t["exit_code"] == 0 else "❌"
        avg_str = f"avg {avg:.1f}s" if avg > 0 else "no history"
        lines.append(
            f"{status} `{t['target']}` — {t['duration']:.1f}s ({avg_str}){anomaly}"
        )

    text = headline + "\n\n" + "\n".join(lines[:30])

    return {
        "text": headline,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Send bullwhip Slack notifications")
    parser.add_argument("--date", required=True, help="date string (YYYY-MM-DD)")
    parser.add_argument("--exit-code", type=int, default=0, help="make exit code (for failure ping)")
    parser.add_argument("--webhook", required=True, help="Slack webhook URL")
    parser.add_argument("--digest", action="store_true", help="send morning digest instead of failure ping")
    parser.add_argument("--log-dir", default="logs", help="logs directory")
    args = parser.parse_args()

    if args.digest:
        payload = build_morning_digest(args.date, args.log_dir)
    else:
        payload = build_failure_ping(args.date, args.exit_code, args.log_dir)

    if send_slack(args.webhook, payload):
        print("[notify_slack] Sent.")
        sys.exit(0)
    else:
        print("[notify_slack] Failed to send.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
