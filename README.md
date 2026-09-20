# bullwhip

A nightly batch data-pipeline framework: **cron + GNU Make + dlt-ops + SQLMesh**.

Modernized from the [original night-shift](https://github.com/soobrosa/night-shift)
(6Wunderkinder, 2013). The scheduler skeleton stays; the workers are replaced
with modern tools. Three ledgers, three read-only projections, one cron line.

## Architecture

```
cron (every 30 min, 00:00–06:00)
  └─ run_workflow.sh          single-flight, bounded attempts, attempt logs
       └─ make -k -j N        the ONLY place cross-system edges exist
            ├─ dlt ingest targets ────▶ warehouse tables (dlt state in destination)
            ├─ sqlmesh.done marker ───▶ sqlmesh run (interval state in warehouse)
            ├─ exports / backups      (fingerprint-gated markers)
            └─ notifications
```

### Division of labor

| Concern | Owner |
|---|---|
| Cadence, retries, locking, attempt logs | cron + `run_workflow.sh` |
| DAG across heterogeneous steps | make |
| Dependency graph inside the warehouse | SQLMesh |
| Incremental state, backfills, restatements | dlt-ops (ingest) / SQLMesh (transform) |
| Data quality | dlt-ops assertions + SQLMesh audits |
| EL ops (validate, gates, ledger, checkpoints, drift) | dlt-ops |
| Metaprogramming | SQLMesh macros + Python models |
| Priority + content sensitivity at the make layer | the three Mara organs |
| Observability / notification / agent access | projections of the ledgers |

## Quick start

### 1. Install dependencies

```bash
pip install -e ".[dev]"          # Python: dlt, dlt-ops, SQLMesh, DuckDB
cd mcp && npm install            # MCP server: @modelcontextprotocol/sdk
# The dashboards in web/ are plain HTML + vanilla JS — nothing to install or build.
```

### 2. Configure

```bash
cp config/bullwhip.sh.sample config/bullwhip.sh
cp config/duckdb.sh.sample config/duckdb.sh
# Edit config/bullwhip.sh: set BULLWHIP_TARGETS, parallel jobs, etc.
# Edit config/duckdb.sh: set DUCKDB_PATH and DATABASE
```

The ingested data ships as Parquet under `data/` (a few KiB, committed).  The
DuckDB warehouse is ephemeral — gitignored, rebuilt from `data/` whenever it
is missing — so the first `make imports` in `examples/github-health/` (or
`make restore`) recreates it and `query.py` works immediately. `logs/` is
ignored, so the dashboards need at least one local or Actions night.

### 3. Run

```bash
# Run the workflow manually:
bash lib/run_workflow.sh

# Or set up cron:
# */30 0-5 * * * bash /path/to/project/lib/run_workflow.sh

# Or let GitHub Actions be the cron: .github/workflows/nightly.yml runs the
# same script at 03:00 UTC daily, keeps warehouse + dlt state + logs in the
# Actions cache, and publishes web/ + logs/ to GitHub Pages when Pages is
# enabled (Settings → Pages → Source: GitHub Actions).  Push and it runs.
```

### 4. Watch

```bash
# Serve the repo root (dashboards + logs + artifacts):
python -m http.server 8765 -d .
# Open: http://localhost:8765/web/index.html
```

Six dashboards read the same night's artifacts (`status.json`,
`timing_env.log`, `ledger.json`, `dag.json`, per-target logs); pick one in the
browser via `?project=<dir>&date=<date>`:

| Dashboard | Idea |
|---|---|
| `web/a.html` | Faithful port of the original Flask look: command Gantt + log debugging |
| `web/b.html` | Observable Plot Gantt + ELK-laid-out DAG with the critical path highlighted |
| `web/c.html` | Mara-style outcome ledger: make exits vs the dlt-ops runs ledger vs warehouse row counts |
| `web/d.html` | Dataroom-style monochrome dashboard: progress/NOW hero, vitals, activity feed, log tree |
| `web/e.html` | A's command Gantt + log debugging views in D's monochrome language |
| `web/f.html` | E with every redundant or non-informative element removed |

`BULLWHIP_LIVE_UI=1` starts the same server automatically during the night.
The pages use relative paths and `logs/index.json` for the night picker, so
`scripts/build_site.sh` can drop them on any static host (the Action does this
for GitHub Pages). Real screenshots from genuine runs are in `docs/visuals/`.

### 5. Agent access

```json
{
  "mcpServers": {
    "bullwhip": {
      "command": "node",
      "args": ["/path/to/bullwhip/mcp/dist/src/index.js"]
    }
  }
}
```

## The components

### lib/ — the scheduler skeleton

- **`run_workflow.sh`** — cron entry point. Single-flight, bounded attempts (default 23), attempt logs, `status.json` heartbeat.
- **`boilerplate.mk`** — included by user Makefiles. Dated targets, the tracking shell, extensible `scaffold`/`nuke`/`cleanup`/`backup` targets.
- **`tracking_shell.py`** — vendored, self-contained. Wraps every make recipe: tees output to per-target logs, writes BEGIN/END JSON to `timing_env.log`. No external dependencies.

### lib/ — the workers

- **`run_pipeline.py`** — thin dlt wrapper CLI, kept as a fallback for simple cases. The primary EL path is `dlt-ops pipeline run`.
- **`connections.py`** — connector registry. DuckDB, MotherDuck, BigQuery, ClickHouse. One config file per connector, same `export KEY="VAL"` convention.
- **`dlt_ops_fallback.py`** — escape hatch only. If `dlt-ops` ever breaks, swap `dlt-ops pipeline run` for this in the makefile. Deliberately incomplete — the full feature set is why we depend on `dlt-ops`.
- **`warehouse_parquet.py`** — export/restore. `export` writes the dataset's raw tables to `data/*.parquet` (the durable copy, run nightly as `backup`); `restore` rebuilds the ephemeral warehouse from them when the file is missing.

### lib/ — the Mara organs

- **`critical_path.py`** — parses the make DAG (`make -pnr`), reads historical durations from `timing_env.log` (summed per target per night), computes longest-downstream-path per target, emits `dag.json` (shared with the UI) and `.WAIT` waves (requires gmake >= 4.4).
- **`fingerprint.py`** — SHA-256 over (recipe + content deps). Stored beside each dated marker. A boilerplate helper refreshes the marker and exits 0 when unchanged. Fixes the silent failure where re-running with edited logic no-ops against yesterday's marker.
- **`run_ledger.py`** — the outcome record. After make finishes, snapshots `dlt-ops pipeline status --json` (runs, records extracted/loaded, errors) and DuckDB row counts into `logs/<date>/ledger.json`. Answers "did the data arrive", not just "did make exit 0".

### sqlmesh/ — the transform layer

- **`config.yaml`** — one gateway per connector, reusing config files for credentials. The nightly recipe runs `plan --no-prompts --auto-apply` (bootstrap, no-op when unchanged) followed by `run` (evaluate completed intervals).
- **`models/`** — SQL models with audits. Replace the old ERB SQL templates.
- **`macros/`** — Python macros, replacing the old `post_process` Ruby blocks.

### web/ — the dashboards

Plain HTML + vanilla JS modules, no build step, no dependencies (option B pulls
Observable Plot + elkjs from the CDN). All six consume `web/shared.js`, which
loads one night's artifacts and derives a single view model: commands from
`timing_env.log` BEGIN/END pairs, per-target state, night state, ledger runs
matched to make targets, and the critical chain from `dag.json`.

- **Live mode** — `a/b/d.html` re-fetch every 3s while the night is running.
- **Archive mode** — pass `?date=<past night>` to inspect history.
- The original Flask UI's Gantt and log-debugging views survive as option A.

### mcp/ — the MCP server

TypeScript, stdio transport. Six read-only tools:

| Tool | What it answers |
|---|---|
| `night_status` | Is the scheduler alive? What attempt are we on? |
| `night_stats` | How many records were extracted/loaded? What are the table row counts and data-layer errors? |
| `list_targets` | What ran, what's running, what failed? |
| `night_summary` | Give me the digest: counts, runtime, failures, data stats, critical path |
| `get_target_log` | Show me the log for target X |
| `explain_critical_path` | Why is the night ordered the way it is? |

The status and stats surfaces have direct parity:

| Static JSON API | MCP |
|---|---|
| `logs/<date>/status.json` | `night_status(date?)` (same fields, plus derived heartbeat age and liveness) |
| `logs/<date>/ledger.json` | `night_stats(date?)` (same runs, record counts, table counts, and errors) |

### lib/ — notifications

- **`notify_slack.py`** — v0 failure ping (stdlib webhook, zero deps) + v1 morning digest with per-target duration vs. historical average. The webhook URL is the credential: locally set `SLACK_WEBHOOK_URL` in `config/bullwhip.sh`; on GitHub Actions it comes from the `SLACK_WEBHOOK_URL` secret (already wired in `nightly.yml`, a silent no-op until the secret exists).

## The three ledgers

| Ledger | What it answers | Where |
|---|---|---|
| `timing_env.log` | What ran at 3am and how long | `logs/<date>/timing_env.log` |
| dlt-ops state | Which source window is loaded + runs ledger | destination `_dlt_loads`/`_dlt_state`/`_dlt_ops_runs` |
| SQLMesh state | Which transform intervals are complete | warehouse `.sqlmesh/` |

None subsumes another. The UI, Slack, and MCP are read-only projections of these ledgers — they never store new state.

## Docker

```bash
docker compose build
docker compose run bullwhip bash    # interactive
docker compose up bullwhip          # run the workflow
```

The Dockerfile builds GNU Make 4.4.1 from source (for `.WAIT` wave support).

## Deployment

Three ways to schedule the night; the container image builds itself.

| Scheduler | Status | Needs |
|---|---|---|
| GitHub Actions (`.github/workflows/nightly.yml`) | primary, verified locally | just push; optionally the `SLACK_WEBHOOK_URL` secret |
| Host cron | works as documented | a crontab line |
| Kubernetes CronJob (`deploy/k8s/cronjob.yaml`) | written, not applied | an image in a registry |

`.github/workflows/docker.yml` runs on every push to `main`: it checks whether
`ghcr.io/<owner>/<repo>:latest` exists and, only when missing, builds and
pushes it (plus a SHA-pinned tag) using the workflow's own `GITHUB_TOKEN` with
`packages: write`. Nothing to configure. Keep the `image:` in
`deploy/k8s/cronjob.yaml` pointing at the same `ghcr.io/<owner>/<repo>` name.

`data/*.parquet` is the durable copy of the ingested data; `warehouse.duckdb`
is rebuilt from it whenever missing, so a cache eviction or fresh clone costs
a re-ingest (the sources merge on primary keys, so it's idempotent) plus a
model refresh — not data loss.

## Lineage

What bullwhip descends from and what it took:

| Ancestor | What bullwhip took | Link |
|---|---|---|
| **night-shift** (soobrosa) | The whole shape: cron + make, `run_workflow.sh` (single-flight, bounded attempts, attempt logs), `boilerplate.mk`, dated `intermediate/<date>/` markers, `timing_env.log`, `attempt_log_sizes.py`, the Flask UI's Gantt and log-debugging views (option A, carried into E and F) | https://github.com/soobrosa/night-shift |
| **trackingshell** (Wunderlist) | `lib/tracking_shell.py` is a self-contained rewrite of its make-shell idea: wrap every recipe, tee per-target logs, BEGIN/END records | https://github.com/wunderlist/trackingshell |
| **Mara** (mara-pipelines) | The three "organs": critical-path priority for make (`critical_path.py`), content-hash cache keys (`fingerprint.py`), and the outcome record "task success is not data success" (`run_ledger.py`, dashboard C) | https://github.com/mara/mara-pipelines |
| **dataroom** (soobrosa) | The monochrome dashboard language of D, E and F: tokens, hairline grid, progress/NOW hero, vitals cells, hatched running bars, tree + preview | https://github.com/soobrosa/dataroom |

## Built on

Runtime, Python (`pyproject.toml`):

| Dependency | By | Role here |
|---|---|---|
| **dlt** (`dlt[duckdb]`) | dltHub | Extract + load; the `github_health` source, schema inference, merge loads |
| **dlt-ops** | [upstream repo — confirm handle/link before publishing] | Project validation, `pipeline run`, runs ledger `_dlt_ops_runs`, schema-drift reconcile, backfill |
| **SQLMesh** (`sqlmesh[duckdb]`) | Tobiko Data | Transform models, intervals, audits, `plan`/`run` |
| **DuckDB** | DuckDB Foundation / DuckDB Labs | The single warehouse file both tools share |
| Optional extras | | `dlt[postgres]`, `dlt[bigquery]` + `google-cloud-bigquery`, `dlt[clickhouse]` + `clickhouse-connect` |

Runtime, non-Python:

| Dependency | Role here |
|---|---|
| **GNU Make** | The DAG. 3.81 (macOS) works; 4.4+ for `.WAIT` waves (Docker image, Ubuntu runners) |
| **bash** + **cron**, or **GitHub Actions** | Cadence. Actions used: `actions/checkout`, `actions/setup-python`, `astral-sh/setup-uv`, `actions/cache`, `actions/upload-artifact`, `actions/upload-pages-artifact`, `actions/configure-pages`, `actions/deploy-pages` |
| **uv** (Astral) | Dependency install in the Action |
| **GitHub REST API** | The example's data source (`GITHUB_TOKEN` in the Action, a PAT locally, or `GITHUB_HEALTH_FIXTURE=1` for none) |
| **Slack incoming webhooks** | Optional failure ping / morning digest |
| **Python 3.11+** | The runtime |

Dashboards and agent access:

| Dependency | Role here |
|---|---|
| **Observable Plot** (`@observablehq/plot@0.4`, jsDelivr) | Dashboard B's Gantt |
| **elkjs** (`elkjs@0.8.2`, jsDelivr) | Dashboard B's DAG layout |
| **@modelcontextprotocol/sdk** | `mcp/` server (TypeScript) |
| Any static file server / GitHub Pages | The dashboards are plain HTML + vanilla JS; `python3 -m http.server` locally |

Dev only: `pytest`, `pytest-cov`, TypeScript + `@types/node` (mcp), Homebrew
`make` (GNU 4.4 on macOS), headless Chrome (the screenshots in `docs/visuals/`).

## Testing

```bash
python -m pytest tests/ -v    # unit tests
bash tests/run.sh             # full test suite + makefile hygiene
```

## License

MIT
