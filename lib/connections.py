#!/usr/bin/env python3
"""Connector registry — one config file per warehouse, shared by dlt and SQLMesh.

Both the EL worker (run_pipeline.py) and the T worker (SQLMesh) import this
module to resolve a connector from a sourced shell config file.  The config
files use the same `export KEY="VAL"` convention that cron already sources,
parsed here with the same regex the old run_sql_template.rb used.

Usage:
    from connections import get_connector
    conn = get_connector("config/duckdb.sh")
    conn.dlt_destination()   # for the EL worker
    conn.sqlmesh_gateway()   # for SQLMesh config
    conn.execute("SELECT 1")  # for ad-hoc queries
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


def parse_config(config_path: str) -> dict[str, str]:
    """Parse `export KEY="VAL"` lines from a shell config file."""
    env: dict[str, str] = {}
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^export\s+(\w+)="([^"]*)"\s*(?:#.*)?$', line.strip())
            if not m:
                m = re.match(r'^export\s+(\w+)=(\S+)\s*(?:#.*)?$', line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


@dataclass
class Connector:
    """Base connector — subclasses implement dlt_destination and execute."""

    env: dict[str, str]

    @property
    def dialect(self) -> str:
        return self.env.get("DIALECT", "duckdb")

    @property
    def database(self) -> str:
        return self.env.get("DATABASE", "")

    def dlt_destination(self):
        """Return a dlt destination object for this connector."""
        raise NotImplementedError

    def dlt_destination_name(self) -> str:
        return self.dialect

    def sqlmesh_gateway_config(self) -> dict[str, Any]:
        """Return SQLMesh gateway connection config."""
        raise NotImplementedError

    def execute(self, query: str) -> list[tuple]:
        """Execute a query and return rows (for ad-hoc use)."""
        raise NotImplementedError

    def connect(self):
        """Return a raw connection object."""
        raise NotImplementedError


class DuckDBConnector(Connector):
    """DuckDB and MotherDuck — same driver, different path."""

    @property
    def is_motherduck(self) -> bool:
        return self.dialect == "motherduck"

    def _duckdb_path(self) -> str:
        if self.is_motherduck:
            token = self.env.get("MOTHERDUCK_TOKEN", "")
            return f"md:{self.database}?motherduck_token={token}"
        return self.env.get("DUCKDB_PATH", "./warehouse.duckdb")

    def dlt_destination(self):
        import dlt

        path = self._duckdb_path()
        return dlt.destinations.duckdb(path)

    def sqlmesh_gateway_config(self) -> dict[str, Any]:
        return {
            "connection": {
                "type": "duckdb",
                "database": self._duckdb_path(),
            }
        }

    def connect(self):
        import duckdb

        return duckdb.connect(self._duckdb_path())

    def execute(self, query: str) -> list[tuple]:
        conn = self.connect()
        try:
            result = conn.execute(query)
            return result.fetchall()
        finally:
            conn.close()


class BigQueryConnector(Connector):
    """BigQuery — google-cloud-bigquery."""

    def dlt_destination(self):
        import dlt

        return dlt.destinations.bigquery(
            project=self.env.get("BIGQUERY_PROJECT", ""),
            dataset=self.database,
            credentials_path=self.env.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        )

    def sqlmesh_gateway_config(self) -> dict[str, Any]:
        return {
            "connection": {
                "type": "bigquery",
                "project": self.env.get("BIGQUERY_PROJECT", ""),
                "dataset": self.database,
            }
        }

    def connect(self):
        from google.cloud import bigquery

        return bigquery.Client(project=self.env.get("BIGQUERY_PROJECT", ""))

    def execute(self, query: str) -> list[tuple]:
        client = self.connect()
        job = client.query(query)
        return [tuple(row) for row in job.result()]


class ClickHouseConnector(Connector):
    """ClickHouse — clickhouse-connect."""

    def dlt_destination(self):
        import dlt

        return dlt.destinations.clickhouse(
            host=self.env.get("CLICKHOUSE_HOST", "localhost"),
            port=int(self.env.get("CLICKHOUSE_PORT", "8123")),
            username=self.env.get("CLICKHOUSE_USER", "default"),
            password=self.env.get("CLICKHOUSE_PASSWORD", ""),
            database=self.database,
        )

    def sqlmesh_gateway_config(self) -> dict[str, Any]:
        return {
            "connection": {
                "type": "clickhouse",
                "host": self.env.get("CLICKHOUSE_HOST", "localhost"),
                "port": int(self.env.get("CLICKHOUSE_PORT", "8123")),
                "username": self.env.get("CLICKHOUSE_USER", "default"),
                "password": self.env.get("CLICKHOUSE_PASSWORD", ""),
                "database": self.database,
            }
        }

    def connect(self):
        import clickhouse_connect

        return clickhouse_connect.get_client(
            host=self.env.get("CLICKHOUSE_HOST", "localhost"),
            port=int(self.env.get("CLICKHOUSE_PORT", "8123")),
            username=self.env.get("CLICKHOUSE_USER", "default"),
            password=self.env.get("CLICKHOUSE_PASSWORD", ""),
            database=self.database,
        )

    def execute(self, query: str) -> list[tuple]:
        client = self.connect()
        result = client.query(query)
        return result.result_rows


CONNECTORS: dict[str, type[Connector]] = {
    "duckdb": DuckDBConnector,
    "motherduck": DuckDBConnector,
    "bigquery": BigQueryConnector,
    "clickhouse": ClickHouseConnector,
}


def get_connector(config_path: str) -> Connector:
    """Resolve a connector from a sourced shell config file."""
    env = parse_config(config_path)
    dialect = env.get("DIALECT", "duckdb")
    cls = CONNECTORS.get(dialect)
    if cls is None:
        raise ValueError(f"Unknown dialect: {dialect!r}. Supported: {list(CONNECTORS)}")
    return cls(env)
