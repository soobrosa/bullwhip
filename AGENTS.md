# Working on Bullwhip

Use the [README](README.md) for the architecture and public CLI,
[`llms.txt`](llms.txt) for the agent-facing usage guide, and the
[tutorial](docs/tutorial.md) for a pipeline walkthrough. The
[build spec](docs/build-spec.md) describes the project from an empty repo;
it is not a request to rebuild the existing project.

## Project boundaries

- Keep cross-system dependencies in GNU Make. The scheduler
  (`pipeline/lib/run_workflow.sh` or GitHub Actions) owns cadence, retries,
  and locking.
  dlt-ops owns ingestion and load outcomes. SQLMesh owns warehouse transforms
  and their state. A successful Make recipe is not evidence of a good load.
- The pipeline runtime lives under `pipeline/` (`lib/`, `sqlmesh/`, `data/`,
  `examples/`). The dlt source packages (`github_health/`, `people_ingest/`)
  and `.dlt/` must stay at the repo root: dlt-ops discovers sources by
  scanning the immediate subdirectories of the directory holding
  `.dlt/config.toml`, with no path override.
- `bullwhip/cli.py` is the packaged entry point. If the demo starts using a
  new pipeline file, check the wheel's `force-include` and uv cache keys in
  `pyproject.toml`. Do not package local credentials, warehouses, or logs.
- Keep `demo` offline after installation and isolated from the caller's
  configuration. `inspect` must not rerun the demo or write to its workspace.
  JSON commands emit one object on stdout; diagnostics go to stderr.
- `bullwhip/daily.py`, `.github/workflows/nightly.yml`, and
  `web/build_site.sh` form the live snapshot path. Keep fixtures and
  failed or historical runs out of the published ranking. Do not silently
  substitute a different date when `daily --date` requests a missing day.
- Treat DuckDB files, local pipeline state, logs, and site output as generated.
  Do not overwrite checked-in Parquet inputs as a side effect of testing.
  The dashboards and MCP server read artifacts; they do not own pipeline state.

## Checks

Run from the repository root with uv, GNU Make, and Bash:

```sh
uv run --no-project --python 3.12 --with '.[dev]' bash tests/run.sh
BULLWHIP_TEST_UVX=1 uv run --no-project --python 3.12 --with '.[dev]' python -m pytest tests/test_uvx_cli.py -q
```

Run the second command for packaging or demo changes; it exercises `uvx`
from outside the checkout. For daily export or site assembly changes, run
`tests/test_daily.py` and check that a missing or failed day does not advance
the latest snapshot. Do not treat a local export test as proof that GitHub
Pages deployed it.

When CLI usage or its JSON contract changes, update the README and
`llms.txt` together. Do not push, release, or dispatch a live workflow unless
the user asks.
