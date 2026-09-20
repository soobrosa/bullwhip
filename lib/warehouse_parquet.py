#!/usr/bin/env python3
"""warehouse_parquet.py — Parquet as the durable copy of the ingested data.

The DuckDB warehouse is deliberately ephemeral (gitignored, wiped between
runs, cold in a fresh cache).  `data/*.parquet` is the source of truth:

  export   write every base table in the dataset schema (the dlt-loaded raw
           tables; `_dlt_*` bookkeeping and SQLMesh views are excluded) to
           <data-dir>/<table>.parquet.  Run nightly as the `backup` target,
           content-hash gated by the caller.

  restore  rebuild the DuckDB file from <data-dir>/*.parquet when it is
           missing (fresh clone, evicted cache, wiped container).  Re-ingest
           after a restore is safe: the sources merge on primary keys, so
           dlt reloads are idempotent, and SQLMesh re-materialises its models
           from the restored tables.
"""

from __future__ import annotations

import argparse
import glob
import os


def dataset_tables(con, dataset: str) -> list[str]:
    """Base tables in the dataset schema, excluding dlt's `_dlt_*` tables.

    Views (SQLMesh's materializations) are not in duckdb_tables() and are
    rebuilt by `sqlmesh run`, so they are never exported.
    """
    rows = con.execute(
        "select table_name from duckdb_tables() where schema_name = ?", [dataset]
    ).fetchall()
    return sorted(r[0] for r in rows if not r[0].startswith("_dlt"))


def export_tables(duckdb_path: str, data_dir: str, dataset: str) -> int:
    """Copy each dataset table to <data_dir>/<table>.parquet. Returns count."""
    import duckdb

    con = duckdb.connect(duckdb_path, read_only=True)
    tables = dataset_tables(con, dataset)
    if not tables:
        print(f"[warehouse_parquet] no tables in {dataset}; nothing to export")
        return 0
    os.makedirs(data_dir, exist_ok=True)
    for t in tables:
        path = os.path.join(data_dir, f"{t}.parquet")
        con.execute(
            f"copy (select * from {dataset}.{t}) to '{path}' (format parquet)"
        )
        rows = con.sql(f"select count(*) from {dataset}.{t}").fetchone()[0]
        print(f"[warehouse_parquet] exported {dataset}.{t} ({rows} rows) -> {path}")
    con.close()
    return len(tables)


def restore_tables(duckdb_path: str, data_dir: str, dataset: str) -> int:
    """Rebuild <duckdb_path> from <data_dir>/*.parquet if missing. Returns count."""
    import duckdb

    parquet_files = sorted(glob.glob(os.path.join(data_dir, "*.parquet")))
    if not parquet_files:
        # First run ever: no durable copy yet. Create an empty warehouse so
        # downstream targets have a file to point at; dlt populates it.
        if not os.path.exists(duckdb_path):
            os.makedirs(os.path.dirname(duckdb_path) or ".", exist_ok=True)
            con = duckdb.connect(duckdb_path)
            con.execute(f"create schema if not exists {dataset}")
            con.close()
            print(f"[warehouse_parquet] no parquet yet; created empty {duckdb_path}")
        else:
            print(f"[warehouse_parquet] no parquet yet; {duckdb_path} already exists")
        return 0
    if os.path.exists(duckdb_path):
        print(f"[warehouse_parquet] {duckdb_path} exists; skipping restore")
        return 0
    os.makedirs(os.path.dirname(duckdb_path) or ".", exist_ok=True)
    con = duckdb.connect(duckdb_path)
    con.execute(f"create schema if not exists {dataset}")
    for pf in parquet_files:
        name = os.path.splitext(os.path.basename(pf))[0]
        con.execute(
            f"create or replace table {dataset}.{name} "
            f"as select * from read_parquet('{pf}')"
        )
        rows = con.sql(f"select count(*) from {dataset}.{name}").fetchone()[0]
        print(f"[warehouse_parquet] restored {dataset}.{name} ({rows} rows) from {pf}")
    con.execute("checkpoint")
    con.close()
    return len(parquet_files)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--duckdb", default=None,
                       help="warehouse file (default: $BULLWHIP_DUCKDB or warehouse.duckdb)")
        p.add_argument("--data-dir", default=None,
                       help="parquet directory (default: data)")
        p.add_argument("--dataset", default=None,
                       help="schema holding the tables (default: $BULLWHIP_DATASET or my_db)")

    p_export = sub.add_parser("export", help="write dataset tables to parquet")
    add_common(p_export)
    p_restore = sub.add_parser("restore", help="rebuild the warehouse from parquet")
    add_common(p_restore)

    args = parser.parse_args()
    duckdb_path = args.duckdb or os.environ.get("BULLWHIP_DUCKDB") or "warehouse.duckdb"
    data_dir = args.data_dir or "data"
    dataset = args.dataset or os.environ.get("BULLWHIP_DATASET") or "my_db"

    if args.command == "export":
        export_tables(duckdb_path, data_dir, dataset)
    else:
        restore_tables(duckdb_path, data_dir, dataset)


if __name__ == "__main__":
    main()
