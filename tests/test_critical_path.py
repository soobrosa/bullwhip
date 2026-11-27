"""Tests for the critical-path priority and DAG parser."""

import json
import os
import tempfile
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "lib"))


def test_parse_timing_env():
    """timing_env.log is parsed into per-target average durations."""
    from critical_path import parse_timing_env

    with tempfile.TemporaryDirectory() as tmpdir:
        date_dir = os.path.join(tmpdir, "2026-09-08")
        os.makedirs(date_dir)
        timing_path = os.path.join(date_dir, "timing_env.log")

        # Write a few BEGIN/END pairs.
        with open(timing_path, "w") as f:
            for i in range(3):
                f.write(json.dumps({
                    "command": "echo test",
                    "target": "target_a",
                    "unique_nr": i * 2,
                    "has_make_level": True,
                    "started_at": f"2026-09-08T03:0{i}:00.000000",
                    "tag": "BEGIN",
                }) + "\n")
                f.write(json.dumps({
                    "command": "echo test",
                    "target": "target_a",
                    "unique_nr": i * 2,
                    "has_make_level": True,
                    "started_at": f"2026-09-08T03:0{i}:00.000000",
                    "finished_at": f"2026-09-08T03:0{i}:1{i}.000000",
                    "exit_code": 0,
                    "tag": "END",
                }) + "\n")

        durations = parse_timing_env(tmpdir)
        assert "target_a" in durations
        assert durations["target_a"] > 0


def test_compute_critical_paths():
    """Critical paths are computed via longest-downstream-path."""
    from critical_path import Target, compute_critical_paths

    targets = {
        "a": Target(name="a", deps=["b"], avg_duration=10),
        "b": Target(name="b", deps=["c"], avg_duration=5),
        "c": Target(name="c", deps=[], avg_duration=3),
    }
    compute_critical_paths(targets)

    # c: 3 (leaf)
    # b: 5 + 3 = 8
    # a: 10 + 8 = 18
    assert targets["c"].longest_downstream == 3
    assert targets["b"].longest_downstream == 8
    assert targets["a"].longest_downstream == 18


def test_compute_depth_waves():
    """Depth waves group targets by topological depth."""
    from critical_path import Target, compute_depth_waves

    targets = {
        "a": Target(name="a", deps=["b"]),
        "b": Target(name="b", deps=["c"]),
        "c": Target(name="c", deps=[]),
    }
    waves = compute_depth_waves(targets)

    assert len(waves) == 3
    assert waves[0] == ["c"]  # depth 0
    assert waves[1] == ["b"]  # depth 1
    assert waves[2] == ["a"]  # depth 2


def test_emit_dag_json():
    """dag.json is emitted with all targets."""
    from critical_path import Target, emit_dag_json

    targets = {
        "a": Target(name="a", deps=["b"], avg_duration=10, longest_downstream=13, depth=1),
        "b": Target(name="b", deps=[], avg_duration=3, longest_downstream=3, depth=0),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        output = os.path.join(tmpdir, "dag.json")
        emit_dag_json(targets, output)
        assert os.path.exists(output)

        with open(output) as f:
            dag = json.load(f)
        assert len(dag["targets"]) == 2
        assert "generated_at" in dag
