#!/usr/bin/env python3
"""critical_path.py — Mara organ 1: critical-path priority for make.

Parses the make DAG (`make -pn`), reads historical durations from
`timing_env.log`, computes the longest-downstream-path per target, and
emits two artifacts:

  1. dag.json — the parsed DAG with historical durations (feeds the UI's
     DAG panel and the priority waves).
  2. A make snippet with .WAIT waves — depth-separated parallel sections
     so long targets run first (requires gmake >= 4.4).

The same pass produces both, so the UI and the priority logic share one
artifact: build once, get both.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Target:
    name: str
    deps: list[str] = field(default_factory=list)
    recipe: str = ""
    avg_duration: float = 0.0  # seconds, from timing_env.log
    longest_downstream: float = 0.0  # critical path length
    depth: int = 0  # topological depth (for .WAIT waves)


def parse_make_dag(makefile_dir: str = ".") -> dict[str, Target]:
    """Parse `make -pn` output into a target → deps map.

    `make -p` prints the database; `-n` means don't run.  We look for
    lines like `target: dep1 dep2` and `#  recipe` entries.
    """
    try:
        # -r drops the built-in suffix rules so only the user's DAG remains.
        result = subprocess.run(
            ["make", "-pnr"],
            capture_output=True,
            text=True,
            cwd=makefile_dir,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    targets: dict[str, Target] = {}
    current_target = None
    not_a_target = False

    for line in result.stdout.splitlines():
        if line.startswith("# Not a target:"):
            # The makefile and its includes appear in the database as files
            # make considered but has no rule for; the next entry is skipped.
            not_a_target = True
            continue
        # Target line: "name: deps" or "name:: deps" (not ":=" assignments).
        m = re.match(r"^([a-zA-Z0-9_./\$(){}-]+)\s*::?\s*(.*)$", line)
        if m and "=" not in line and not line.startswith("\t"):
            if not_a_target:
                not_a_target = False
                current_target = None
                continue
            name = m.group(1)
            # Special targets (.PHONY, .SUFFIXES, .DEFAULT, ...) and stale
            # suffix rules all start with a dot.
            if name.startswith("."):
                current_target = None
                continue
            # "|" separates order-only prerequisites; they still gate the
            # target, so keep them as deps but drop the separator itself.
            deps = [d for d in m.group(2).split() if d and d != "|"]
            if name not in targets:
                targets[name] = Target(name=name)
            # Double-colon rules list the same target several times; merge.
            for d in deps:
                if d not in targets[name].deps:
                    targets[name].deps.append(d)
            current_target = name
        elif line.startswith("\t") and current_target:
            # Recipe line
            recipe = line.strip()
            if recipe and not recipe.startswith("#"):
                targets[current_target].recipe += recipe + "\n"
        elif not line.startswith("#") and line.strip() == "":
            not_a_target = False

    return targets


def parse_timing_env(log_dir: str) -> dict[str, float]:
    """Parse timing_env.log and return average duration per target (seconds).

    A target's duration for one night is the sum of all its recipe commands
    (each command gets its own BEGIN/END pair); the average is across nights.
    """
    durations: dict[str, list[float]] = defaultdict(list)

    # Walk all date directories.
    if not os.path.isdir(log_dir):
        return {}

    for date_dir in sorted(os.listdir(log_dir)):
        timing_path = os.path.join(log_dir, date_dir, "timing_env.log")
        if not os.path.exists(timing_path):
            continue
        per_night: dict[str, float] = defaultdict(float)
        begin_records: dict[int, dict] = {}
        try:
            with open(timing_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key = rec.get("unique_nr")
                    if key is None:
                        continue
                    if rec.get("tag") == "BEGIN":
                        begin_records[key] = rec
                    elif rec.get("tag") == "END" and key in begin_records:
                        begin = begin_records.pop(key)
                        try:
                            start = datetime.fromisoformat(begin["started_at"])
                            end = datetime.fromisoformat(rec["finished_at"])
                            dur = (end - start).total_seconds()
                            target = rec.get("target", "")
                            per_night[target] += dur
                        except (KeyError, ValueError):
                            pass
        except IOError:
            continue
        for target, total in per_night.items():
            durations[target].append(total)

    # Average per target.
    return {
        target: sum(durs) / len(durs)
        for target, durs in durations.items()
        if durs
    }


def scope_to_entries(
    targets: dict[str, Target], entries: list[str]
) -> dict[str, Target]:
    """Keep only targets reachable from the entry targets (plus themselves).

    `make -pnr` dumps the whole database, including helper targets (`all`,
    `list-all-targets`, `backfill`, …) the night never touches.  Walk the
    dependency edges from the entries — the same goals run_workflow.sh passes
    to make — and drop everything not reached.  If no entry matches (e.g. a
    bare `--print-waves` run outside a project), return the unscoped dict so
    the caller still gets a useful DAG.
    """
    if not entries:
        return targets
    stack = [e for e in entries if e in targets]
    if not stack:
        return targets  # nothing matched; don't emit an empty DAG
    reachable: set[str] = set()
    while stack:
        name = stack.pop()
        if name in reachable:
            continue
        reachable.add(name)
        stack.extend(targets[name].deps)
    return {name: t for name, t in targets.items() if name in reachable}


def compute_critical_paths(targets: dict[str, Target]) -> None:
    """Compute longest-downstream-path per target via memoized DFS."""
    visiting: set[str] = set()

    def dfs(name: str) -> float:
        if name not in targets:
            return 0.0
        t = targets[name]
        if t.longest_downstream > 0:
            return t.longest_downstream
        if name in visiting:
            return 0.0  # cycle guard
        visiting.add(name)
        downstream = 0.0
        for dep in t.deps:
            downstream = max(downstream, dfs(dep))
        t.longest_downstream = t.avg_duration + downstream
        visiting.discard(name)
        return t.longest_downstream

    for name in targets:
        dfs(name)


def compute_depth_waves(targets: dict[str, Target]) -> list[list[str]]:
    """Group targets into depth waves for .WAIT parallelism.

    Depth 0 = no deps (leaf targets).  Depth N = max depth of deps + 1.
    Targets in the same wave can run in parallel; waves are separated by .WAIT.
    """
    depth_cache: dict[str, int] = {}

    def depth(name: str) -> int:
        if name in depth_cache:
            return depth_cache[name]
        if name not in targets:
            return 0
        if not targets[name].deps:
            depth_cache[name] = 0
            return 0
        depth_cache[name] = 1 + max(depth(d) for d in targets[name].deps)
        return depth_cache[name]

    waves: dict[int, list[str]] = defaultdict(list)
    for name in targets:
        d = depth(name)
        targets[name].depth = d
        waves[d].append(name)

    # Sort each wave by critical path (longest first).
    for wave_targets in waves.values():
        wave_targets.sort(
            key=lambda t: targets[t].longest_downstream if t in targets else 0,
            reverse=True,
        )

    return [waves[i] for i in sorted(waves.keys())]


def emit_dag_json(targets: dict[str, Target], output_path: str) -> None:
    """Emit dag.json — the shared artifact for the UI and priority logic."""
    nodes = []
    for name, t in targets.items():
        nodes.append({
            "id": name,
            "deps": t.deps,
            "recipe": t.recipe.strip(),
            "avg_duration": round(t.avg_duration, 2),
            "longest_downstream": round(t.longest_downstream, 2),
            "depth": t.depth,
        })
    dag = {
        "targets": nodes,
        "generated_at": datetime.now().isoformat(),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dag, f, indent=2)
    print(f"[critical_path] Wrote {output_path} ({len(nodes)} targets)")


def emit_wait_snippet(waves: list[list[str]], output_path: str | None = None) -> str:
    """Emit a make snippet with .WAIT waves for depth-based parallelism."""
    lines = ["# Auto-generated by critical_path.py — .WAIT waves for priority scheduling."]
    lines.append("# Requires gmake >= 4.4 for .WAIT support.")
    lines.append("")

    for i, wave in enumerate(waves):
        if i > 0:
            lines.append(".WAIT")
        lines.append(f"# Wave {i} (depth {i}): {len(wave)} targets")
        for target in wave:
            lines.append(f"#   {target} (critical path: ?s)")

    snippet = "\n".join(lines) + "\n"
    if output_path:
        with open(output_path, "w") as f:
            f.write(snippet)
        print(f"[critical_path] Wrote {output_path} ({len(waves)} waves)")
    return snippet


def main():
    parser = argparse.ArgumentParser(description="Compute critical paths and .WAIT waves")
    parser.add_argument("--makefile-dir", default=".", help="directory containing the Makefile")
    parser.add_argument("--log-dir", default="logs", help="logs directory for timing_env.log")
    parser.add_argument("--dag-output", default="dag.json", help="output path for dag.json")
    parser.add_argument("--wait-output", default=None, help="output path for .WAIT make snippet")
    parser.add_argument("--print-waves", action="store_true", help="print .WAIT waves to stdout")
    parser.add_argument(
        "--targets",
        default=None,
        help="space/comma-separated entry targets the night runs (default: "
        "BULLWHIP_TARGETS + BULLWHIP_FAILURE_TARGETS from the environment); "
        "dag.json is scoped to these and their transitive deps",
    )
    args = parser.parse_args()

    # Parse the make DAG.
    targets = parse_make_dag(args.makefile_dir)
    if not targets:
        print("[critical_path] No targets found.", file=sys.stderr)
        sys.exit(1)

    # Scope to what the night actually runs.
    entry_names = [
        t
        for t in re.split(r"[,\s]+", args.targets or "")
        if t
    ] or [
        t
        for t in re.split(
            r"[,\s]+",
            os.environ.get("BULLWHIP_TARGETS", "")
            + " "
            + os.environ.get("BULLWHIP_FAILURE_TARGETS", ""),
        )
        if t
    ]
    total = len(targets)
    targets = scope_to_entries(targets, entry_names)
    if len(targets) < total:
        print(
            f"[critical_path] Scoped to {len(targets)} of {total} targets "
            f"reachable from: {' '.join(entry_names)}"
        )

    # Read historical durations.
    durations = parse_timing_env(args.log_dir)
    for name, t in targets.items():
        t.avg_duration = durations.get(name, 0.0)

    # Compute critical paths.
    compute_critical_paths(targets)

    # Compute depth waves.
    waves = compute_depth_waves(targets)

    # Emit artifacts.
    emit_dag_json(targets, args.dag_output)

    if args.print_waves:
        emit_wait_snippet(waves, args.wait_output)
        if not args.wait_output:
            print(emit_wait_snippet(waves))
    elif args.wait_output:
        emit_wait_snippet(waves, args.wait_output)

    # Print summary.
    print(f"[critical_path] {len(targets)} targets, {len(waves)} waves")
    for i, wave in enumerate(waves):
        total_duration = sum(
            targets[t].avg_duration for t in wave if t in targets
        )
        print(f"  Wave {i}: {len(wave)} targets, ~{total_duration:.1f}s total")


if __name__ == "__main__":
    main()
