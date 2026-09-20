"""Tests for lib/warehouse_parquet.py — export/restore round trip."""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import warehouse_parquet as wp  # noqa: E402


def _seed(db_path):
    """Create a warehouse with a data table, a _dlt_ table, and a view."""
    con = duckdb.connect(db_path)
    con.execute("create schema my_db")
    con.execute(
        "create table my_db.repos_metadata as "
        "select * from (values ('a', 1), ('b', 2)) as t(name, stars)"
    )
    con.execute("create table my_db._dlt_loads as select * from (values ('x')) as t(id)")
    con.execute("create view my_db.github_health as select 1 as one")
    con.close()


def test_export_round_trip(tmp_path):
    """Export writes the data table only; restore rebuilds it faithfully."""
    db = tmp_path / "wh.duckdb"
    data_dir = tmp_path / "data"
    _seed(str(db))

    n = wp.export_tables(str(db), str(data_dir), "my_db")
    assert n == 1  # _dlt_* skipped; views are not in duckdb_tables()
    assert [f.name for f in data_dir.glob("*.parquet")] == ["repos_metadata.parquet"]

    db.unlink()
    n = wp.restore_tables(str(db), str(data_dir), "my_db")
    assert n == 1
    con = duckdb.connect(str(db), read_only=True)
    rows = con.sql("select name, stars from my_db.repos_metadata order by name").fetchall()
    con.close()
    assert rows == [("a", 1), ("b", 2)]


def test_restore_skips_when_db_exists(tmp_path, capsys):
    """An existing warehouse is never clobbered by a direct restore call."""
    db = tmp_path / "wh.duckdb"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(str(db))
    duckdb.sql(f"copy (select 42 as v) to '{data_dir}/x.parquet' (format parquet)")

    n = wp.restore_tables(str(db), str(data_dir), "my_db")
    assert n == 0
    assert "skipping restore" in capsys.readouterr().out


def test_restore_without_parquet_creates_empty_warehouse(tmp_path):
    """First run ever (no durable copy): just ensure the file exists."""
    db = tmp_path / "wh.duckdb"
    n = wp.restore_tables(str(db), str(tmp_path / "data"), "my_db")
    assert n == 0
    assert db.exists()
