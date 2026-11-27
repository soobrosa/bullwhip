#!/usr/bin/env python3
"""fingerprint.py — Mara organ 2: content-hash cache keys.

SHA-256 over (recipe command + declared content deps).  Stored beside each
dated marker.  A boilerplate.mk helper at the top of every recipe refreshes
the marker and exits 0 when unchanged.

Fixes the silent failure where re-running with edited logic no-ops against
yesterday's marker: the old dated-target system only knew *when* a target
ran, never *whether the inputs changed*.

Usage in a Makefile recipe (check and work MUST share one shell — make runs
each recipe line in its own shell, so a bare `exit 0` cannot skip the rest;
recipe lines below start with a literal tab, as make requires):
intermediate/$(TODAY)/my_target.done: | scaffold
	@python pipeline/lib/fingerprint.py --check --target $@ \
	    --recipe "$(strip $(MAKECMD))" \
	    --deps "$(filter %.py %.sql %.sh,$^)" \
	|| { \
	    # ... actual recipe ...; \
	    python pipeline/lib/fingerprint.py --write --target $@ \
	        --recipe "$(strip $(MAKECMD))" \
	        --deps "$(filter %.py %.sql %.sh,$^)"; \
	}

Scope: exports, backups, notifications, and any target whose inputs aren't
file-mtimes.  SQLMesh and dlt manage their own state; they don't need this.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def compute_hash(recipe: str, deps: str) -> str:
    """SHA-256 over the recipe command + content of declared deps."""
    h = hashlib.sha256()
    h.update(recipe.encode("utf-8"))
    h.update(b"\x00")  # separator

    if deps:
        for dep_path in deps.split():
            dep_path = dep_path.strip()
            if not dep_path or not os.path.isfile(dep_path):
                continue
            try:
                with open(dep_path, "rb") as f:
                    h.update(f.read())
                h.update(b"\x00")
            except IOError:
                continue

    return h.hexdigest()


def get_fingerprint_path(target: str) -> str:
    """Return the path to the fingerprint file beside a marker."""
    return target + ".fingerprint"


def write_fingerprint(target: str, recipe: str, deps: str) -> str:
    """Write the fingerprint file and return the hash."""
    fp = get_fingerprint_path(target)
    os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
    hash_val = compute_hash(recipe, deps)
    data = {
        "target": target,
        "hash": hash_val,
        "recipe": recipe,
        "deps": deps,
    }
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return hash_val


def check_fingerprint(target: str, recipe: str, deps: str) -> bool:
    """Return True if the fingerprint matches (recipe+deps unchanged)."""
    fp = get_fingerprint_path(target)
    if not os.path.exists(fp):
        return False

    try:
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False

    current_hash = compute_hash(recipe, deps)
    return data.get("hash") == current_hash


def main():
    parser = argparse.ArgumentParser(description="Content-hash fingerprint for make markers")
    parser.add_argument("--target", required=True, help="marker target path")
    parser.add_argument("--recipe", default="", help="the recipe command string")
    parser.add_argument("--deps", default="", help="space-separated content dep paths")
    parser.add_argument("--check", action="store_true",
                        help="check if fingerprint matches; exit 0 if match, 1 if not")
    parser.add_argument("--write", action="store_true",
                        help="write the fingerprint file after successful recipe execution")
    args = parser.parse_args()

    if args.check:
        if check_fingerprint(args.target, args.recipe, args.deps):
            # Fingerprint matches — refresh the marker and exit 0.
            Path(args.target).touch()
            print(f"[fingerprint] {args.target}: unchanged, skipping")
            sys.exit(0)
        else:
            print(f"[fingerprint] {args.target}: changed, will run")
            sys.exit(1)

    if args.write:
        hash_val = write_fingerprint(args.target, args.recipe, args.deps)
        print(f"[fingerprint] {args.target}: wrote {hash_val[:12]}")
        sys.exit(0)

    # Default: just print the hash.
    print(compute_hash(args.recipe, args.deps))


if __name__ == "__main__":
    main()
