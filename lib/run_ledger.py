#!/usr/bin/env python3
"""run_ledger.py — Mara organ: the outcome record.

A green make marker only proves a command exited 0.  This script snapshots
what the data layer says happened tonight and writes it next to the make logs
as logs/<date>/ledger.json, so the UI can show "rows loaded" beside "exit 0".

Sources, both optional and best-effort:
  * `dlt-ops pipeline status --json`  — the _dlt_ops_runs ledger (records
    extracted/loaded, status, error summary per run)
  * the DuckDB warehouse                — row counts per table in the dataset

Never fails the night: any error is recorded in the JSON under "errors".
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys


def dlt_ops_runs(root: str, since: datetime.datetime, limit: int) -> tuple[list[dict], str | None]:
    """Runs from the dlt-ops ledger that started at or after `since` (UTC)."""
    try:
        proc = subprocess.run(
            ["dlt-ops", "pipeline", "status", "--json", "--limit", str(limit)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [], f"dlt-ops status: {exc}"
    if proc.returncode != 0:
        return [], f"dlt-ops status exit {proc.returncode}: {proc.stderr.strip()[:300]}"
    try:
        sources = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return [], f"dlt-ops status: unparsable JSON ({exc})"

    runs: list[dict] = []
    for src in sources:
        for run in src.get("runs") or []:
            started = run.get("started_at")
            try:
                started_dt = datetime.datetime.fromisoformat(started) if started else None
            except ValueError:
                started_dt = None
            if started_dt is not None and started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=datetime.timezone.utc)
            if started_dt is None or started_dt >= since:
                runs.append(run)
    return runs, None


def duckdb_table_counts(db_path: str, dataset: str) -> tuple[dict[str, int], str | None]:
    try:
        import duckdb  # noqa: WPS433 — optional dependency
    except ImportError:
        return {}, "duckdb not installed"
    if not os.path.exists(db_path):
        return {}, f"warehouse not found: {db_path}"
    try:
        con = duckdb.connect(db_path, read_only=True)
        tables = [
            r[0]
            for r in con.execute(
                "select table_name from information_schema.tables "
                "where table_schema = ? and table_name not like '\\_dlt%' escape '\\' "
                "order by table_name",
                [dataset],
            ).fetchall()
        ]
        counts = {}
        for t in tables:
            counts[t] = con.execute(f'select count(*) from "{dataset}"."{t}"').fetchone()[0]
        con.close()
        return counts, None
    except Exception as exc:  # noqa: BLE001 — best effort, report and move on
        return {}, f"duckdb: {exc}"


def build_ledger(root: str, since: datetime.datetime, db_path: str | None, dataset: str, limit: int) -> dict:
    errors: list[str] = []
    runs, err = dlt_ops_runs(root, since, limit)
    if err:
        errors.append(err)
    tables: dict[str, int] = {}
    if db_path:
        tables, err = duckdb_table_counts(db_path, dataset)
        if err:
            errors.append(err)

    loaded = sum(r.get("records_loaded") or 0 for r in runs)
    extracted = sum(r.get("records_extracted") or 0 for r in runs)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "since": since.isoformat(),
        "runs": runs,
        "records_extracted": extracted,
        "records_loaded": loaded,
        "tables": tables,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot the data-layer outcome of tonight's run")
    parser.add_argument("--root", default=".", help="dlt-ops project root (where .dlt/ lives)")
    parser.add_argument("--out", required=True, help="path of ledger.json to write")
    parser.add_argument("--since", help="ISO timestamp; only dlt-ops runs started after this count")
    parser.add_argument("--duckdb", help="DuckDB warehouse path for table row counts")
    parser.add_argument("--dataset", default="my_db")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    if args.since:
        since = datetime.datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.astimezone()
    else:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    ledger = build_ledger(args.root, since, args.duckdb, args.dataset, args.limit)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, default=str)
    print(
        f"[run_ledger] {len(ledger['runs'])} dlt-ops runs, "
        f"{ledger['records_loaded']} records loaded, {len(ledger['tables'])} tables"
        + (f", {len(ledger['errors'])} errors" if ledger["errors"] else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
