#!/usr/bin/env python3
"""Query the github_health results from the DuckDB warehouse."""

import sys
from pathlib import Path

import duckdb


def main():
    # Warehouse lives at the project root (../../warehouse.duckdb from here).
    warehouse = Path(__file__).resolve().parent.parent.parent / "warehouse.duckdb"
    try:
        conn = duckdb.connect(str(warehouse), read_only=True)
        rows = conn.execute("""
            SELECT full_name, stargazers_count, contributor_count, bus_factor,
                   health_status, days_since_push
            FROM my_db.github_health
            ORDER BY stargazers_count DESC
        """).fetchall()
        conn.close()
    except Exception:
        print("  (warehouse not built yet — run 'make imports' first)")
        return

    if not rows:
        print("  (no data — run 'make imports' first)")
        return

    print("=== Repo Health ===")
    for row in rows:
        print(f"  {row[0]:30s} stars={row[1]:>6}  contribs={row[2]:>3}  "
              f"bus={row[3]:>2}  {row[4]:15s}  last_push={row[5]}d ago")


if __name__ == "__main__":
    main()
