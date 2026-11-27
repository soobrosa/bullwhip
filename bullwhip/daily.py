"""Export and read the nightly GitHub Trending rankings."""

import argparse
import json
from datetime import date
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


PUBLISHED_LOGS = "https://soobrosa.info/bullwhip/pipeline/examples/github-health/logs"
TRENDING_SOURCE = "https://github.com/trending"


def snapshot_date(value: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except (TypeError, ValueError):
        pass
    raise argparse.ArgumentTypeError("date must be YYYY-MM-DD")


def fetch_snapshot(day: str | None = None) -> dict:
    path = f"{day}/trending.json" if day is not None else "trending-latest.json"
    name = day or "the latest night"
    try:
        with urlopen(f"{PUBLISHED_LOGS}/{path}", timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"no daily snapshot published for {name}") from exc
        raise ValueError(f"could not fetch the daily snapshot: HTTP {exc.code}") from exc
    except (OSError, HTTPException) as exc:
        raise ValueError(f"could not fetch the daily snapshot: {exc}") from exc
    except ValueError as exc:
        raise ValueError("the published daily snapshot is not valid JSON") from exc

    try:
        actual = snapshot_date(result["date"])
        if (day is not None and actual != day) or result["source"] != TRENDING_SOURCE:
            raise ValueError
        if not isinstance(result["repos"], list) or not result["repos"]:
            raise ValueError
    except (KeyError, TypeError, ValueError, argparse.ArgumentTypeError) as exc:
        raise ValueError("the published daily snapshot has an unexpected format or date") from exc
    return result


def export_snapshot(warehouse: Path, day: str, output: Path) -> None:
    import duckdb

    try:
        with duckdb.connect(str(warehouse), read_only=True) as con:
            # A same-day rerun merges by repo, so older rows for repos no
            # longer trending can remain. Use only the most recent load.
            result = con.execute("""
                SELECT rank, full_name, total_stars, stars_today, language
                FROM my_db.trending_repos
                WHERE snapshot_date = ?
                QUALIFY _dlt_load_id = max(_dlt_load_id) OVER ()
                ORDER BY rank, full_name
            """, [day])
            columns = [column[0] for column in result.description]
            repos = [dict(zip(columns, row)) for row in result.fetchall()]
    except duckdb.Error as exc:
        raise ValueError(f"cannot read trending rankings from the warehouse: {exc}") from exc
    if not repos:
        raise ValueError(f"warehouse has no trending rankings for {day}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"date": day, "source": TRENDING_SOURCE, "repos": repos}) + "\n",
        encoding="utf-8",
    )


def export_main() -> int:
    parser = argparse.ArgumentParser(description="Export a single night's live trending rankings")
    parser.add_argument("--warehouse", required=True, type=Path)
    parser.add_argument("--date", required=True, type=snapshot_date)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        export_snapshot(args.warehouse, args.date, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"bullwhip: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(export_main())
