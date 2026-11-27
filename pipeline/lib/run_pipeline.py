#!/usr/bin/env python3
"""run_pipeline.py — the dlt EL worker convention.

Wraps a dlt pipeline in a thin CLI that make invokes as a subprocess.
The make target stays a dated-file idempotency marker; dlt's own state
(loaded windows, incremental cursors) lives in the destination.

Usage:
    python pipeline/lib/run_pipeline.py --config config/duckdb.sh \
        --source my_source.people --write-disposition merge

    python pipeline/lib/run_pipeline.py --config config/duckdb.sh \
        --source sql_database --table people \
        --incremental updated_at --write-disposition merge
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from the project root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from connections import get_connector


def build_sql_database_source(args, connector):
    """Build a dlt source from a SQL database (the incremental_load case)."""
    import dlt

    source = dlt.sources.sql_database(
        credentials=f"postgresql://{connector.env.get('PGUSER', '')}:"
        f"{connector.env.get('PGPASSWORD', '')}@"
        f"{connector.env.get('PGHOST', 'localhost')}:"
        f"{connector.env.get('PGPORT', '5432')}/"
        f"{connector.env.get('PGDATABASE', '')}",
        schema=args.schema,
    )

    table = source(args.table, table_adapter_callback=None)

    if args.incremental:
        table = table.with_incremental(args.incremental, initial_value=None)

    return table


def run_pipeline(args):
    connector = get_connector(args.config)
    destination = connector.dlt_destination()

    import dlt

    pipeline = dlt.pipeline(
        pipeline_name=args.pipeline_name,
        destination=destination,
        dataset_name=connector.database,
    )

    if args.source_type == "sql_database":
        source = build_sql_database_source(args, connector)
    else:
        # Generic: source name is a dotted path to a dlt source factory.
        # e.g. "my_source.people" imports my_source and calls .people()
        parts = args.source.split(".")
        module_name = parts[0]
        attr_path = parts[1:]
        import importlib

        mod = importlib.import_module(module_name)
        source = mod
        for attr in attr_path:
            source = getattr(source, attr)
        if callable(source):
            source = source()

    result = pipeline.run(
        source,
        write_disposition=args.write_disposition,
        table_name=args.table,
    )

    # Print a summary to stdout (captured by tracking_shell).
    print(f"[run_pipeline] Loaded {result.metrics.get('rows', '?')} rows "
          f"into {args.table or args.source}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="dlt EL pipeline runner")
    parser.add_argument("--config", required=True, help="connector config file")
    parser.add_argument("--source", required=True, help="source name (e.g. sql_database or my_source.people)")
    parser.add_argument("--source-type", default="sql_database",
                        help="source type: sql_database or generic")
    parser.add_argument("--table", default=None, help="destination table name")
    parser.add_argument("--schema", default=None, help="source schema name")
    parser.add_argument("--incremental", default=None,
                        help="incremental column name (e.g. updated_at)")
    parser.add_argument("--write-disposition", default="append",
                        choices=["append", "replace", "merge"],
                        help="dlt write disposition")
    parser.add_argument("--pipeline-name", default="bullwhip",
                        help="dlt pipeline name (for state isolation)")
    args = parser.parse_args()

    try:
        sys.exit(run_pipeline(args))
    except Exception as e:
        print(f"[run_pipeline] FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
