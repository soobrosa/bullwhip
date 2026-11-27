"""Tests for parse_make_dag() and the critical_path CLI main().

parse_make_dag() shells out to `make -pn`, so we build a real Makefile in a
temp directory and let make parse it.  The CLI main() is exercised by
monkeypatching sys.argv.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "lib"))

import critical_path  # noqa: E402

# `make` is required for parse_make_dag; skip the DAG tests if it's absent.
HAS_MAKE = shutil.which("make") is not None


pytestmark = pytest.mark.skipif(not HAS_MAKE, reason="make not installed")


def _write_makefile(tmp_path):
    """Write a small Makefile with a known DAG into tmp_path."""
    (tmp_path / "Makefile").write_text(
        ".PHONY: all\n"
        "all: dep1 dep2\n"
        "dep1:\n"
        "\techo building dep1\n"
        "dep2: dep3\n"
        "\techo building dep2\n"
        "dep3:\n"
        "\techo building dep3\n"
    )


def test_parse_make_dag_finds_targets(tmp_path):
    """parse_make_dag parses the targets and their dependencies."""
    _write_makefile(tmp_path)
    targets = critical_path.parse_make_dag(str(tmp_path))
    # Our explicit targets must be present.
    assert "all" in targets
    assert "dep1" in targets
    assert "dep2" in targets
    assert "dep3" in targets
    # Dependencies are parsed correctly.
    assert set(targets["all"].deps) == {"dep1", "dep2"}
    assert targets["dep2"].deps == ["dep3"]
    assert targets["dep3"].deps == []
    # Recipe lines are captured.
    assert "echo building dep1" in targets["dep1"].recipe


def test_parse_make_dag_returns_empty_on_missing_makefile(tmp_path):
    """A directory with no Makefile yields an empty (or make-error) result."""
    # make -pn in an empty dir returns its built-in rules; our targets won't
    # be there.  We just assert no exception and a dict result.
    targets = critical_path.parse_make_dag(str(tmp_path))
    assert isinstance(targets, dict)
    # Our targets are definitely absent.
    assert "all" not in targets or "dep1" not in targets


def test_parse_make_dag_handles_make_timeout(monkeypatch, tmp_path):
    """A make timeout returns an empty dict rather than raising."""
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="make", timeout=30)

    monkeypatch.setattr(subprocess, "run", boom)
    targets = critical_path.parse_make_dag(str(tmp_path))
    assert targets == {}


# ---------------------------------------------------------------------------
# emit_wait_snippet
# ---------------------------------------------------------------------------

def test_emit_wait_snippet_waves():
    """emit_wait_snippet produces .WAIT-separated wave sections."""
    waves = [["c"], ["b"], ["a"]]
    snippet = critical_path.emit_wait_snippet(waves)
    assert ".WAIT" in snippet
    assert "Wave 0" in snippet
    assert "Wave 1" in snippet
    assert "Wave 2" in snippet
    assert "#   c" in snippet


def test_emit_wait_snippet_writes_file(tmp_path):
    """When given an output path, the snippet is written to disk."""
    out = tmp_path / "waves.mk"
    critical_path.emit_wait_snippet([["c"], ["b"]], str(out))
    assert out.exists()
    content = out.read_text()
    assert ".WAIT" in content


# ---------------------------------------------------------------------------
# scope_to_entries
# ---------------------------------------------------------------------------

def test_scope_to_entries_keeps_reachable_only():
    """Only the entry targets and their transitive deps survive scoping."""
    targets = {
        "imports": critical_path.Target(name="imports", deps=["build"]),
        "build": critical_path.Target(name="build", deps=["ingest"]),
        "ingest": critical_path.Target(name="ingest"),
        "backfill": critical_path.Target(name="backfill"),
        "status": critical_path.Target(name="status"),
    }
    scoped = critical_path.scope_to_entries(targets, ["imports"])
    assert set(scoped) == {"imports", "build", "ingest"}
    assert "backfill" not in scoped and "status" not in scoped


def test_scope_to_entries_with_relative_target_and_input_file(tmp_path):
    example = tmp_path / "examples" / "fixture"
    example.mkdir(parents=True)
    (tmp_path / "input.csv").touch()
    (example / "Makefile").write_text(
        "imports: | ../../warehouse.duckdb\n"
        "../../warehouse.duckdb: ../../input.csv\n"
        "\ttouch $@\n"
    )
    targets = critical_path.parse_make_dag(str(example))
    scoped = critical_path.scope_to_entries(targets, ["imports"])
    assert set(scoped) == {"imports", "../../warehouse.duckdb"}
    assert scoped["imports"].deps == ["../../warehouse.duckdb"]
    assert scoped["../../warehouse.duckdb"].deps == ["../../input.csv"]


def test_scope_to_entries_empty_or_unknown_returns_all():
    """No entries (or none matching) falls back to the unscoped DAG."""
    targets = {"a": critical_path.Target(name="a"), "b": critical_path.Target(name="b")}
    assert set(critical_path.scope_to_entries(targets, [])) == {"a", "b"}
    assert set(critical_path.scope_to_entries(targets, ["nope"])) == {"a", "b"}


# ---------------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------------

def test_main_emits_dag_json(tmp_path, monkeypatch, capsys):
    """main() parses the Makefile and writes dag.json."""
    _write_makefile(tmp_path)
    dag_out = tmp_path / "dag.json"
    monkeypatch.setattr(
        sys, "argv",
        [
            "critical_path.py",
            "--makefile-dir", str(tmp_path),
            "--log-dir", str(tmp_path / "logs"),
            "--dag-output", str(dag_out),
        ],
    )
    # main() returns normally on success (it only sys.exit(1)s on no targets).
    critical_path.main()
    assert dag_out.exists()
    dag = json.loads(dag_out.read_text())
    names = {n["id"] for n in dag["targets"]}
    assert {"all", "dep1", "dep2", "dep3"}.issubset(names)
    assert "generated_at" in dag


def test_main_scopes_to_targets(tmp_path, monkeypatch):
    """--targets scopes dag.json to the entries and their transitive deps."""
    _write_makefile(tmp_path)
    dag_out = tmp_path / "dag.json"
    monkeypatch.setattr(
        sys, "argv",
        [
            "critical_path.py",
            "--makefile-dir", str(tmp_path),
            "--log-dir", str(tmp_path / "logs"),
            "--dag-output", str(dag_out),
            "--targets", "dep2",
        ],
    )
    critical_path.main()
    dag = json.loads(dag_out.read_text())
    names = {n["id"] for n in dag["targets"]}
    assert names == {"dep2", "dep3"}


def test_main_print_waves(tmp_path, monkeypatch, capsys):
    """--print-waves prints the .WAIT snippet to stdout."""
    _write_makefile(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        [
            "critical_path.py",
            "--makefile-dir", str(tmp_path),
            "--log-dir", str(tmp_path / "logs"),
            "--dag-output", str(tmp_path / "dag.json"),
            "--print-waves",
        ],
    )
    critical_path.main()
    out = capsys.readouterr().out
    assert ".WAIT" in out
    assert "Wave" in out


def test_main_writes_wait_output(tmp_path, monkeypatch):
    """--wait-output writes the .WAIT snippet to a file."""
    _write_makefile(tmp_path)
    wait_out = tmp_path / "waves.mk"
    monkeypatch.setattr(
        sys, "argv",
        [
            "critical_path.py",
            "--makefile-dir", str(tmp_path),
            "--log-dir", str(tmp_path / "logs"),
            "--dag-output", str(tmp_path / "dag.json"),
            "--wait-output", str(wait_out),
        ],
    )
    critical_path.main()
    assert wait_out.exists()
    assert ".WAIT" in wait_out.read_text()


def test_main_no_targets_exits_one(tmp_path, monkeypatch):
    """When make yields no targets, main() exits 1."""
    # Patch parse_make_dag to return empty to simulate the no-targets case.
    monkeypatch.setattr(
        sys, "argv",
        [
            "critical_path.py",
            "--makefile-dir", str(tmp_path),
            "--log-dir", str(tmp_path / "logs"),
            "--dag-output", str(tmp_path / "dag.json"),
        ],
    )
    monkeypatch.setattr(critical_path, "parse_make_dag", lambda *a, **k: {})
    with pytest.raises(SystemExit) as exc:
        critical_path.main()
    assert exc.value.code == 1
