"""Run the GitHub health demo or read published nightly rankings."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from .daily import fetch_snapshot, snapshot_date


EXAMPLE = Path("pipeline/examples/github-health")


def copy_demo(root: Path) -> None:
    package = Path(__file__).resolve().parent
    bundled = package / "_demo"
    if bundled.is_dir():
        shutil.copytree(bundled, root, dirs_exist_ok=True)
    else:
        # Editable installs read the same explicit file map as the wheel.
        import tomllib

        source = package.parent
        with (source / "pyproject.toml").open("rb") as file:
            wheel = tomllib.load(file)["tool"]["hatch"]["build"]["targets"]["wheel"]
        for name, destination in wheel["force-include"].items():
            target = root / Path(destination).relative_to("bullwhip/_demo")
            if (source / name).is_dir():
                shutil.copytree(source / name, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, target)
    (root / "pipeline/lib/tracking_shell.py").chmod(0o755)


def inspect_demo(root: Path, night: str) -> dict:
    import duckdb

    logs = root / EXAMPLE / "logs" / date.fromisoformat(night).isoformat()
    ledger = json.loads((logs / "ledger.json").read_text(encoding="utf-8"))
    dag = json.loads((logs / "dag.json").read_text(encoding="utf-8"))
    warehouse = root / "warehouse.duckdb"
    try:
        with duckdb.connect(str(warehouse), read_only=True) as con:
            result = con.execute("""
                SELECT full_name, stargazers_count, contributor_count, bus_factor, health_status
                FROM my_db.github_health
                ORDER BY stargazers_count DESC, full_name
            """)
            columns = [column[0] for column in result.description]
            repos = [dict(zip(columns, row)) for row in result.fetchall()]
    except duckdb.Error as exc:
        raise ValueError(f"cannot read demo warehouse: {exc}") from exc

    return {
        "directory": str(root),
        "date": night,
        "warehouse": str(warehouse),
        "logs": str(logs),
        "ledger": ledger,
        "dag": dag,
        "repos": repos,
    }


def run_demo(root: Path | None) -> dict:
    # Make recipes must use the Python tools installed by uvx rather than
    # commands from the caller's project or virtual environment.
    path = os.pathsep.join((str(Path(sys.executable).parent), os.environ.get("PATH", os.defpath)))
    if not shutil.which("make", path=path) or not Path("/bin/bash").is_file():
        raise ValueError("the demo requires GNU Make and /bin/bash (Linux or macOS)")

    if root is None:
        root = Path(tempfile.mkdtemp(prefix="bullwhip-demo-"))
    else:
        root.mkdir()
    root = root.resolve()
    copy_demo(root)

    # Start from a clean environment: don't read someone's dlt config, load
    # the live GitHub source, or inherit make flags from a parent process.
    home = root / ".home"
    home.mkdir()
    night = date.today().isoformat()
    env = {
        "PATH": path,
        "HOME": str(home),
        "GITHUB_HEALTH_FIXTURE": "1",
        "DESTINATION__DUCKDB__CREDENTIALS": "warehouse.duckdb",
        "RUNTIME__DLTHUB_TELEMETRY": "false",
        "SQLMESH__DISABLE_ANONYMIZED_ANALYTICS": "1",
        "TODAY": night,
    }
    example = root / EXAMPLE
    logs = example / "logs" / night
    logs.mkdir(parents=True)
    warehouse = root / "warehouse.duckdb"
    commands = [
        (example, ["make", "-k", "imports", "backup"]),
        (root, [
            sys.executable, "pipeline/lib/run_ledger.py", "--since",
            datetime.now(timezone.utc).isoformat(), "--duckdb", str(warehouse),
            "--out", str(logs / "ledger.json"),
        ]),
        (root, [
            sys.executable, "pipeline/lib/critical_path.py", "--makefile-dir", str(example),
            "--log-dir", str(logs.parent), "--targets", "imports backup",
            "--dag-output", str(logs / "dag.json"),
        ]),
    ]
    run_log = logs / "attempt-00.log"
    with run_log.open("w", encoding="utf-8") as output:
        for cwd, command in commands:
            proc = subprocess.run(
                command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT,
            )
            if proc.returncode:
                name = Path(command[1] if command[0] == sys.executable else command[0]).name
                raise ValueError(f"{name} exited {proc.returncode}; see {run_log}")

    result = inspect_demo(root, night)
    if result["ledger"]["errors"] or not result["ledger"]["records_loaded"] or not result["repos"]:
        raise ValueError(f"demo ran but did not produce a clean data load; see {run_log}")
    (logs.parent / "index.json").write_text(json.dumps([night]), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="bullwhip", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run the fixture pipeline in a fresh workspace")
    demo.add_argument("--directory", type=Path, help="new directory (default: a temporary directory)")
    inspect = commands.add_parser("inspect", help="read a completed demo without rerunning it")
    inspect.add_argument("directory", type=Path, help="workspace printed by demo")
    for command in (demo, inspect):
        command.add_argument("--json", action="store_true", help="print one JSON object to stdout")
    daily = commands.add_parser("daily", help="print published GitHub Trending rankings as JSON")
    daily.add_argument("--date", type=snapshot_date, help="snapshot date in UTC (default: latest published)")
    args = parser.parse_args()
    try:
        if args.command == "daily":
            print(json.dumps(fetch_snapshot(args.date)))
            return 0
        if args.command == "demo":
            result = run_demo(args.directory)
        else:
            root = args.directory.resolve()
            index = root / EXAMPLE / "logs/index.json"
            night, = json.loads(index.read_text(encoding="utf-8"))
            result = inspect_demo(root, night)
    except (OSError, ValueError) as exc:
        print(f"bullwhip: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result))
    else:
        print(f"Demo workspace: {result['directory']}")
        print(f"{result['ledger']['records_loaded']} records loaded; {len(result['repos'])} repos scored")
        for repo in result["repos"]:
            print(f"  {repo['full_name']}: {repo['health_status']}")
        print(f"Logs: {result['logs']}")
    return 0
