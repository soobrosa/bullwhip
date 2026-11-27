"""Tests for pipeline/lib/run_ledger.py — the outcome record (Mara organ 3)."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "lib"))

import run_ledger


LEDGER_JSON = json.dumps([
    {
        "source": "github_health",
        "ledger": "ok",
        "error": None,
        "runs": [
            {
                "run_id": "abc123",
                "started_at": "2026-09-08T19:30:05.248527+00:00",
                "completed_at": "2026-09-08T19:30:05.563800+00:00",
                "status": "failed",
                "records_extracted": None,
                "records_loaded": None,
                "error_summary": "PipelineStepFailed: connection refused",
                "resource_name": None,
                "source_section": "github_health",
            },
            {
                "run_id": "def456",
                "started_at": "2026-09-08T19:27:37.036188+00:00",
                "completed_at": "2026-09-08T19:27:38.323185+00:00",
                "status": "completed",
                "records_extracted": 21,
                "records_loaded": 21,
                "error_summary": None,
                "resource_name": None,
                "source_section": "github_health",
            },
        ],
    }
])


def test_dlt_ops_runs_filters_by_since(monkeypatch):
    """Only runs started at/after `since` count toward the night."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=LEDGER_JSON, stderr="")

    monkeypatch.setattr(run_ledger.subprocess, "run", fake_run)
    since = __import__("datetime").datetime.fromisoformat("2026-09-08T19:29:00+00:00")
    runs, err = run_ledger.dlt_ops_runs(".", since, 50)
    assert err is None
    assert [r["run_id"] for r in runs] == ["abc123"]


def test_dlt_ops_runs_missing_cli_is_recorded_not_raised(monkeypatch):
    """A broken dlt-ops becomes an error entry, never a crash."""

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("dlt-ops")

    monkeypatch.setattr(run_ledger.subprocess, "run", fake_run)
    runs, err = run_ledger.dlt_ops_runs(".", __import__("datetime").datetime.now(__import__("datetime").timezone.utc), 50)
    assert runs == []
    assert err and "dlt-ops" in err


def test_duckdb_table_counts_excludes_dlt_tables():
    duckdb = pytest.importorskip("duckdb")
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "warehouse.duckdb")
        con = duckdb.connect(db)
        con.execute("create schema my_db")
        con.execute("create table my_db.repos_metadata (repo varchar)")
        con.execute("insert into my_db.repos_metadata values ('a'), ('b'), ('c')")
        con.execute("create table my_db._dlt_loads (x integer)")  # ledger tables are excluded
        con.close()

        counts, err = run_ledger.duckdb_table_counts(db, "my_db")
        assert err is None
        assert counts == {"repos_metadata": 3}


def test_build_ledger_aggregates(monkeypatch):
    since = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    monkeypatch.setattr(
        run_ledger, "dlt_ops_runs",
        lambda root, since, limit: ([{"records_loaded": 21, "records_extracted": 21, "status": "completed"}], None),
    )
    monkeypatch.setattr(
        run_ledger, "duckdb_table_counts",
        lambda db, dataset: ({"repos_metadata": 3, "github_health": 3}, None),
    )
    ledger = run_ledger.build_ledger(".", since, "warehouse.duckdb", "my_db", 50)
    assert ledger["records_loaded"] == 21
    assert ledger["tables"] == {"repos_metadata": 3, "github_health": 3}
    assert ledger["runs"][0]["status"] == "completed"
    assert ledger["errors"] == []


def test_build_ledger_collects_errors_from_both_sources(monkeypatch):
    since = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    monkeypatch.setattr(run_ledger, "dlt_ops_runs", lambda root, since, limit: ([], "dlt-ops status: boom"))
    monkeypatch.setattr(run_ledger, "duckdb_table_counts", lambda db, dataset: ({}, "duckdb: locked"))
    ledger = run_ledger.build_ledger(".", since, None, "my_db", 50)
    # db_path=None means the warehouse was not consulted — only one error then.
    assert ledger["errors"] == ["dlt-ops status: boom"]
    assert ledger["records_loaded"] == 0
