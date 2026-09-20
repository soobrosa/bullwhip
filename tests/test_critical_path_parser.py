"""Tests for the make -pnr DAG parser fixes and per-night duration sums.

These exercise the real make binary (like test_critical_path_dag.py) because
the parser's job is exactly to survive make's database format: "# Not a
target:" entries, double-colon rules, order-only prerequisites, and built-in
suffix rules.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

MAKEFILE = """
# Exercises the parser: double-colon rules, order-only prereqs, dated paths.
inter/2026-01-01/:
	mkdir -p $@

logs/2026-01-01/:
	mkdir -p $@

x.done: inter/2026-01-01/ | inter/2026-01-01/
	touch x.done

scaffold:: inter/2026-01-01/
scaffold:: logs/2026-01-01/

imports: scaffold x.done
"""

skip_needs_make = pytest.mark.skipif(
    os.system("make --version >/dev/null 2>&1") != 0, reason="make not available"
)


@skip_needs_make
def test_parse_make_dag_merges_double_colon_rules():
    from critical_path import parse_make_dag

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "makefile").write_text(MAKEFILE)
        targets = parse_make_dag(tmpdir)

        # The two scaffold:: rules merge into one dep list, no duplicates.
        # (make's database strips trailing slashes from prerequisite names.)
        assert "scaffold" in targets
        assert targets["scaffold"].deps == ["inter/2026-01-01", "logs/2026-01-01"]


@skip_needs_make
def test_parse_make_dag_drops_separator_keeps_order_only():
    from critical_path import parse_make_dag

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "makefile").write_text(MAKEFILE)
        targets = parse_make_dag(tmpdir)

        # The "|" separator is not a prerequisite; the order-only dir still is.
        assert "|" not in targets["x.done"].deps
        assert "inter/2026-01-01" in targets["x.done"].deps


@skip_needs_make
def test_parse_make_dag_skips_makefile_and_dot_targets():
    from critical_path import parse_make_dag

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "makefile").write_text(MAKEFILE)
        targets = parse_make_dag(tmpdir)

        # "makefile" is marked "# Not a target:"; built-in rules start with ".".
        assert "makefile" not in targets
        assert not [name for name in targets if name.startswith(".")]


def test_parse_timing_env_sums_commands_per_night():
    """A target's night duration is the SUM of its commands, averaged over nights."""
    from critical_path import parse_timing_env

    with tempfile.TemporaryDirectory() as tmpdir:
        night1 = os.path.join(tmpdir, "2026-09-08")
        night2 = os.path.join(tmpdir, "2026-09-09")
        os.makedirs(night1)
        os.makedirs(night2)

        def record(nr, target, start, end, tag):
            rec = {
                "command": "cmd", "target": target, "unique_nr": nr,
                "started_at": start, "tag": tag,
            }
            if tag == "END":
                rec["finished_at"] = end
                rec["exit_code"] = 0
            return json.dumps(rec) + "\n"

        # Night 1: two commands for target_a, 1s + 2s = 3s for the night.
        with open(os.path.join(night1, "timing_env.log"), "w") as f:
            f.write(record(1, "target_a", "2026-09-08T03:00:00", "2026-09-08T03:00:01", "BEGIN"))
            f.write(record(1, "target_a", "2026-09-08T03:00:00", "2026-09-08T03:00:01", "END"))
            f.write(record(2, "target_a", "2026-09-08T03:00:01", "2026-09-08T03:00:03", "BEGIN"))
            f.write(record(2, "target_a", "2026-09-08T03:00:01", "2026-09-08T03:00:03", "END"))
            # target_b also runs that night: 10s.
            f.write(record(3, "target_b", "2026-09-08T03:00:00", "2026-09-08T03:00:10", "BEGIN"))
            f.write(record(3, "target_b", "2026-09-08T03:00:00", "2026-09-08T03:00:10", "END"))

        # Night 2: target_a runs once, 5s.
        with open(os.path.join(night2, "timing_env.log"), "w") as f:
            f.write(record(4, "target_a", "2026-09-09T03:00:00", "2026-09-09T03:00:05", "BEGIN"))
            f.write(record(4, "target_a", "2026-09-09T03:00:00", "2026-09-09T03:00:05", "END"))

        durations = parse_timing_env(tmpdir)
        assert durations["target_a"] == pytest.approx((3 + 5) / 2)  # per-night sums, averaged
        assert durations["target_b"] == pytest.approx(10)
