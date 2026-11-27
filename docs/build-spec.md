# Bullwhip build specification

This is the specification for rebuilding Bullwhip in an empty Git
repository. For changes to the existing repository, see [AGENTS.md](../AGENTS.md).

Build Bullwhip from scratch in the empty repository. Implement it, run the
tests, and document how to use it. Do not clone or copy an existing Bullwhip
implementation. Do not push, deploy, or create a release unless asked.

Bullwhip is a standalone Python 3.12 CLI for an inspectable nightly batch
pipeline. Its reference pipeline tracks the daily GitHub Trending rankings
and enriches them with public repository metadata. Keep it small: one
machine, one DuckDB warehouse, no daemon or hosted orchestrator.

## CLI

- Package a `bullwhip` entry point with `pyproject.toml`. Users must be able
  to run it from outside the checkout. No PyPI release is required:
  ```sh
  uvx --python 3.12 --from 'git+https://github.com/<owner>/<repo>.git@main' bullwhip daily
  ```
- `bullwhip daily` prints one JSON object with `date` (UTC), `source`, and
  `repos` in Trending rank order. Include rank, repository name, total stars,
  stars gained that day, and language. `--date YYYY-MM-DD` reads that
  published day. No token or local warehouse is needed. Never substitute
  fixture data or silently return a different date for an explicit request.
- `bullwhip demo --json` runs the same pipeline on bundled deterministic
  fixtures. After installation, it must work offline and without credentials.
  Use a fresh workspace and return its location, the DuckDB and log paths,
  the load ledger, the Make DAG, and the scored repos. Support an optional
  `--directory PATH`; refuse to overwrite an existing directory.
- `bullwhip inspect <directory> --json` reads the completed demo without
  rerunning it or changing files. Keep stdout clean for JSON and send
  diagnostics to stderr with a nonzero exit on failure.

## Pipeline and daily publishing

- Use cron or GitHub Actions for scheduling, GNU Make for cross-system
  dependencies, dlt-ops for ingestion and data checks, and SQLMesh for
  warehouse transforms and audits. Make retries bounded and single-flight.
  Use dated completion markers and content fingerprints where appropriate.
- Track trending rank, rank movement, star growth, and repo health. Keep
  task timing, load outcomes, and SQLMesh state distinct. Record real row
  counts and errors: a successful subprocess is not proof that data arrived.
  Export raw tables to Parquet so the warehouse can be rebuilt.
- Schedule the live run at 03:00 UTC. Publish dated JSON and a latest pointer
  via GitHub Pages only after a successful live run with data. Failed runs,
  fixture runs, and historical dispatches must not advance the pointer.
  Keep the previous snapshot date visible when today's is unavailable.
- Provide a static dashboard and a read-only stdio MCP server for status,
  run summaries, target logs, and critical-path inspection. Both should read
  the run artifacts, not maintain their own state.

## Documentation and acceptance

- Put the `uvx` commands at the top of `README.md`. Write a standalone
  `llms.txt` with copy-paste commands, JSON fields, and error behavior, plus a
  tutorial that walks through ingestion, transforms, and inspecting a run.
- Exercise the packaged CLI from a clean directory. Run the demo with network
  access blocked after installation. Verify that `inspect` returns the same
  JSON without changing artifacts. Exercise publication and retrieval for
  two different dates, a missing date, and a failed or fixture run that
  leaves the last good snapshot intact.
- Report what you ran and what passed. Distinguish local verification from
  anything that still needs a GitHub Actions or Pages deployment.
