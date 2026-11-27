#!/usr/bin/env python3
"""dlt-ops fallback wrapper — escape hatch, not primary implementation.

The primary path is the `dlt-ops` package (pip install dlt-ops), which ships:
  - pipeline validate (21 static rules, import sandbox, runtime re-checked)
  - pre-load assertions with quarantine (_dlt_rejected table)
  - in-destination runs ledger (_dlt_ops_runs) + pipeline status
  - checkpoints, backfill, schema-drift reconciliation (both directions)
  - custom predicates, TOML-declared assertions

This file exists so that if dlt-ops ever breaks or feels heavy, you can
swap `dlt-ops pipeline run` for `python pipeline/lib/dlt_ops_fallback.py` in the
makefile and keep the three ideas that matter: assertions, runs ledger,
and the hard/soft failure split.  It is deliberately incomplete — the
full feature set is why we depend on dlt-ops.

Usage (escape hatch only):
    python pipeline/lib/dlt_ops_fallback.py --config config/duckdb.sh \
        --source people_ingest --table people \
        --assertion "row_count:min=0" --assertion "unique:id" \
        --write-disposition merge
"""

from __future__ import annotations

import argparse
import datetime
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connections import get_connector


class AssertionResult:
    def __init__(self, name: str, passed: bool, hard: bool = True, message: str = ""):
        self.name = name
        self.passed = passed
        self.hard = hard
        self.message = message

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "hard": self.hard, "message": self.message}


def run_assertions(conn, table_name: str, assertions: list[str]) -> list[AssertionResult]:
    """Run pre-load assertions.  Supported: row_count:min/max, not_null, unique, soft: prefix."""
    results: list[AssertionResult] = []
    for assertion in assertions:
        is_soft = assertion.startswith("soft:")
        if is_soft:
            assertion = assertion[5:]
        hard = not is_soft

        if assertion.startswith("row_count:"):
            constraints = assertion[len("row_count:"):].split(",")
            min_count = max_count = None
            for c in constraints:
                if c.startswith("min="):
                    min_count = int(c[4:])
                elif c.startswith("max="):
                    max_count = int(c[4:])
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}")[0][0]
            if min_count is not None and count < min_count:
                results.append(AssertionResult(assertion, False, hard, f"Row count {count} < min {min_count}"))
            elif max_count is not None and count > max_count:
                results.append(AssertionResult(assertion, False, hard, f"Row count {count} > max {max_count}"))
            else:
                results.append(AssertionResult(assertion, True, hard))
        elif assertion.startswith("not_null:"):
            col = assertion[len("not_null:"):]
            nulls = conn.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {col} IS NULL")[0][0]
            results.append(AssertionResult(assertion, nulls == 0, hard,
                f"Column '{col}' has {nulls} NULLs" if nulls > 0 else ""))
        elif assertion.startswith("unique:"):
            col = assertion[len("unique:"):]
            dups = conn.execute(f"SELECT COUNT(*) FROM (SELECT {col} FROM {table_name} GROUP BY {col} HAVING COUNT(*) > 1)")[0][0]
            results.append(AssertionResult(assertion, dups == 0, hard,
                f"Column '{col}' has {dups} duplicate values" if dups > 0 else ""))
        else:
            results.append(AssertionResult(assertion, False, False, f"Unknown assertion: {assertion}"))
    return results


def ensure_runs_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _dlt_ops_runs (
            run_id VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP,
            source VARCHAR, table_name VARCHAR, status VARCHAR,
            rows_loaded INTEGER, assertions TEXT, duration_seconds FLOAT)
    """)


def main():
    parser = argparse.ArgumentParser(description="dlt-ops fallback (escape hatch only — prefer `dlt-ops pipeline run`)")
    parser.add_argument("--config", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--write-disposition", default="append", choices=["append", "replace", "merge"])
    parser.add_argument("--incremental", default=None)
    parser.add_argument("--assertion", action="append", default=[])
    args = parser.parse_args()

    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.datetime.now()

    connector = get_connector(args.config)
    conn = connector.connect()

    import dlt
    pipeline = dlt.pipeline(pipeline_name=f"ops_{args.table}", destination=connector.dlt_destination(), dataset_name=connector.database)
    source = dlt.sources.sql_database(credentials=f"postgresql://{connector.env.get('PGUSER', '')}:{connector.env.get('PGPASSWORD', '')}@{connector.env.get('PGHOST', 'localhost')}:{connector.env.get('PGPORT', '5432')}/{connector.env.get('PGDATABASE', '')}")
    table = source(args.table)
    if args.incremental:
        table = table.with_incremental(args.incremental)

    pre_assertions = []
    if args.assertion:
        pipeline.run(table, table_name=f"_{args.table}_staging", write_disposition="replace")
        pre_assertions = run_assertions(conn, f"_{args.table}_staging", args.assertion)

    hard_failures = [a for a in pre_assertions if not a.passed and a.hard]
    status = "succeeded"
    rows_loaded = 0

    if hard_failures:
        status = "failed_hard"
        print(f"[fallback] HARD FAILURE: {len(hard_failures)} assertions failed")
        for a in hard_failures:
            print(f"  ✗ {a.name}: {a.message}")
    else:
        result = pipeline.run(table, table_name=args.table, write_disposition=args.write_disposition)
        rows_loaded = result.metrics.get("rows", 0) if hasattr(result, "metrics") else 0
        soft_warnings = [a for a in pre_assertions if not a.passed and not a.hard]
        if soft_warnings:
            status = "succeeded_with_warnings"
            for a in soft_warnings:
                print(f"  ⚠ {a.name}: {a.message}")

    finished_at = datetime.datetime.now()
    duration = (finished_at - started_at).total_seconds()

    ensure_runs_table(conn)
    conn.execute("INSERT INTO _dlt_ops_runs VALUES (?,?,?,?,?,?,?,?,?)",
        [run_id, started_at, finished_at, args.source, args.table, status, rows_loaded, str([a.to_dict() for a in pre_assertions]), duration])
    conn.close()

    print(f"[fallback] Run {run_id}: {status} ({duration:.1f}s, {rows_loaded} rows)")
    sys.exit(1 if status == "failed_hard" else 0)


if __name__ == "__main__":
    main()
