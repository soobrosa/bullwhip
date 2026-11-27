"""Tests for the connector registry."""

import os
import tempfile
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "lib"))


def test_parse_config():
    """Config files are parsed correctly."""
    from connections import parse_config

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write('export DIALECT="duckdb"\n')
        f.write('export DUCKDB_PATH="./test.duckdb"\n')
        f.write('export DATABASE="my_db"\n')
        f.write('# this is a comment\n')
        f.write('export EMPTY=""\n')
        f.name = f.name  # keep reference
        path = f.name

    try:
        env = parse_config(path)
        assert env["DIALECT"] == "duckdb"
        assert env["DUCKDB_PATH"] == "./test.duckdb"
        assert env["DATABASE"] == "my_db"
        assert env["EMPTY"] == ""
    finally:
        os.unlink(path)


def test_get_connector_duckdb():
    """DuckDB connector is resolved correctly."""
    from connections import get_connector, DuckDBConnector

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write('export DIALECT="duckdb"\n')
        f.write('export DUCKDB_PATH=":memory:"\n')
        f.write('export DATABASE="test_db"\n')
        path = f.name

    try:
        conn = get_connector(path)
        assert isinstance(conn, DuckDBConnector)
        assert conn.dialect == "duckdb"
        assert conn.database == "test_db"
    finally:
        os.unlink(path)


def test_get_connector_unknown_dialect():
    """Unknown dialects raise ValueError."""
    from connections import get_connector

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write('export DIALECT="oracle"\n')
        path = f.name

    try:
        with pytest.raises(ValueError, match="Unknown dialect"):
            get_connector(path)
    finally:
        os.unlink(path)


def test_duckdb_execute():
    """DuckDB connector can execute queries."""
    pytest.importorskip("duckdb")
    from connections import get_connector

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write('export DIALECT="duckdb"\n')
        f.write('export DUCKDB_PATH=":memory:"\n')
        f.write('export DATABASE="test_db"\n')
        path = f.name

    try:
        conn = get_connector(path)
        result = conn.execute("SELECT 1 AS val")
        assert result == [(1,)]
    finally:
        os.unlink(path)
