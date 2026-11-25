# Tutorial: Track GitHub trending-repo health with bullwhip

This tutorial walks through building a real pipeline that scrapes GitHub's
daily trending repos and tracks their stars, growth, and health metrics. It
serves as both the runnable example and the getting-started guide.

To try the fixture pipeline without a checkout or configuration, start with
the [standalone CLI demo](../README.md#try-it-with-uvx). The steps below are
for working on the pipeline from the source tree.

## What we're building

A nightly pipeline that:
1. **Ingests** the day's trending ranking plus repo metadata, contributors, releases, and star snapshots from github.com/trending and the GitHub API (or fixture data)
2. **Transforms** them with SQLMesh into health scores (bus factor, staleness, growth rate)
3. **Exposes** the results through the live UI, Slack notifications, and an MCP server

```
cron (every 30 min)
  └─ run_workflow.sh
       ├─ make -k -j imports
       │    ├─ dlt-ops pipeline validate --strict            (project checks)
       │    ├─ dlt-ops pipeline run -s github_health -y      (ingest + assertions + runs ledger)
       │    ├─ dlt-ops pipeline reconcile --all              (schema-drift detection)
       │    └─ sqlmesh --gateway prod plan --auto-apply      (health models)
       ├─ make backup
       ├─ run_ledger.py     → logs/<date>/ledger.json        (what the data layer says happened)
       └─ critical_path.py  → logs/<date>/dag.json           (DAG + tonight's timings)

make query                                                 (you, in the morning)
```

## Prerequisites

- Python 3.11–3.13
- GNU Make (macOS system make works; gmake 4.4+ in the Docker image for `.WAIT` waves)
- No GitHub token needed for fixture mode

## Step 1: Install

```bash
cd /path/to/bullwhip
pip install -e ".[dev]"
```

This installs dlt, dlt-ops, SQLMesh, and DuckDB.

## Step 2: Configure

The dlt-ops project config is already set up at `.dlt/config.toml`. Every
night the source scrapes [github.com/trending](https://github.com/trending)
and tracks that day's trending repos — the list changes on its own, so there
are no repos to configure. (There is no official trending API; the scraper
is the fragile part, and fixture mode keeps the tutorial running when it
breaks.)

For real GitHub data (not fixture), copy `.dlt/secrets.toml.sample` to
`.dlt/secrets.toml` (gitignored) and add your token:

```toml
[sources.github_health.credentials]
token = "ghp_your_token_here"
```

Or skip the file and use dlt's environment-variable form, which is what the
GitHub Action does (Step 7):

```bash
export DESTINATION__DUCKDB__CREDENTIALS=warehouse.duckdb
export SOURCES__GITHUB_HEALTH__CREDENTIALS__TOKEN=ghp_your_token_here
```

## Step 3: Run the pipeline (fixture mode)

```bash
cd examples/github-health
GITHUB_HEALTH_FIXTURE=1 make imports
```

This runs the full chain (about 7 seconds on fixture data):
1. `dlt-ops pipeline validate --strict` — validates the project layout, config and source
2. `dlt-ops pipeline run -s github_health -y` — ingests fixture data into DuckDB
3. `dlt-ops pipeline reconcile --all --include-removal` — checks for schema drift
4. `sqlmesh --gateway prod plan --no-prompts --auto-apply && sqlmesh --gateway prod run`
   — builds the health models. `plan` bootstraps `prod` on a fresh warehouse and
   is a no-op when nothing changed; `run` evaluates the models whose daily
   interval has completed. Two runs on the same calendar day refresh the raw
   tables but not the models (`run` says "No models are ready to run").

Every recipe command goes through `lib/tracking_shell.py`, so you also get
`logs/<date>/timing_env.log` and one log file per target.

To run it again from scratch: `make nuke` drops the markers, the warehouse and
the dlt pipeline state.

## Step 4: See the results

```bash
make query
```

Output on fixture data:
```
=== Repo Health ===
  pallets/flask                  stars= 67000  contribs=  4  bus= 1  bus-factor-risk  last_push=2d ago
  duckdb/duckdb                  stars= 28000  contribs=  3  bus= 1  bus-factor-risk  last_push=1d ago
  tikv/tikv                      stars= 15000  contribs=  5  bus= 1  bus-factor-risk  last_push=1d ago
```

`bus` is the number of contributors needed to cover 50% of contributions. The
fixture gives every repo one dominant contributor, hence `bus= 1` across the
board; against the real API (Step 5) the numbers differ per repo.

## Step 5: Run the pipeline (real GitHub data)

```bash
# Set your token in .dlt/secrets.toml first, then:
make imports
```

Same pipeline, real data. dlt-ops handles:
- **Pre-load assertions**: row count floors, uniqueness checks
- **Runs ledger**: every run writes to `_dlt_ops_runs` in DuckDB
- **Schema-drift reconciliation**: detects new columns and columns that went dark
- **Import sandbox**: catches source modules that make network calls at import time

## Step 6: Watch it live

Start the live UI:

```bash
# From the project root:
python -m http.server 8765 -d .
# Open: http://localhost:8765/web/index.html
```

The dashboards all read the same files under `examples/github-health/logs/<date>/`
and take `?project=examples/github-health&date=<date>`:
- **A (Flask port)** — command Gantt, log debugging with expandable per-target logs
- **B (Plot + ELK)** — chart Gantt plus the make DAG (currently broken: its chart libraries fail to load)
- **C (outcome ledger)** — make exits side by side with the dlt-ops runs ledger and warehouse row counts
- **D (monochrome)** — progress, NOW line, vitals, activity feed, log tree + preview
- **E / F (monochrome Gantt + log debugging)** — A's two views in D's language; F is E with
  everything that doesn't carry information removed. Start with F.

Each re-fetches every 3s while the night is running. Without `?date=` a
dashboard shows the viewer's local today, or, if that night has no artifacts
yet, the most recent night in `logs/index.json` (written by `run_workflow.sh`;
this is also how the picker works on GitHub Pages, which has no directory
listings). Real screenshots from real runs, with provenance, are in
`docs/visuals/`.

## Step 7: Set up cron

`lib/run_workflow.sh` always changes to the repo root first, sources
`config/bullwhip.sh`, then changes into `BULLWHIP_PROJECT_DIR` (relative
to the root) to run make. So the crontab line is just the script's path:

```bash
# Copy the config
cp config/bullwhip.sh.sample config/bullwhip.sh

# Edit config/bullwhip.sh:
export BULLWHIP_PROJECT_DIR="examples/github-health"
export BULLWHIP_TARGETS="imports"
export BULLWHIP_DUCKDB="$BULLWHIP_ROOT/warehouse.duckdb"   # for ledger.json row counts
export GITHUB_HEALTH_FIXTURE=1                                  # drop for real data

# Add to crontab:
*/30 0-5 * * * bash /path/to/bullwhip/lib/run_workflow.sh
```

The workflow runs every 30 minutes from midnight to 6am and retries a failed
night up to `BULLWHIP_MAX_ATTEMPTS` (default 23) times; make's dated markers
mean a retry only redoes what failed. After each attempt it writes
`status.json` (heartbeat), `ledger.json` (dlt-ops runs + warehouse row counts)
and `dag.json` (DAG with tonight's timings) next to the logs. On the final
attempt it sends a Slack ping if `BULLWHIP_NOTIFY=slack` and anything failed.

To try a night by hand, including a past date:

```bash
bash lib/run_workflow.sh                          # tonight
BULLWHIP_DATE=2026-09-07 bash lib/run_workflow.sh   # a specific night
```

### Or: GitHub Actions instead of cron

`.github/workflows/nightly.yml` runs the same `lib/run_workflow.sh` with the
same `config/bullwhip.sh` at 03:00 UTC every day, against the real GitHub
API using the workflow's own `GITHUB_TOKEN`. Push the repo to GitHub and it is
scheduled; nothing else to configure. Optionally enable Pages (Settings → Pages →
Source: **GitHub Actions**) and the dashboards go live at
`https://<you>.github.io/<repo>/`, reading every night that has run so far.

What differs from cron, and why:

| | cron | Action |
|---|---|---|
| Retries | one attempt per 30-min tick, up to 23 | three attempts a minute apart inside one job (`BULLWHIP_FAIL_FAST=1`, `BULLWHIP_MAX_ATTEMPTS=2`) |
| State between nights | the filesystem | `actions/cache`: `warehouse.duckdb`, `.dlt-data/` (dlt pipeline state, via `DLT_DATA_DIR`), `examples/github-health/logs/` |
| Secrets | `.dlt/secrets.toml` | env vars `DESTINATION__DUCKDB__CREDENTIALS`, `SOURCES__GITHUB_HEALTH__CREDENTIALS__TOKEN=${{ secrets.GITHUB_TOKEN }}` |
| Output | files on the box | job summary (`status.json`, ledger, `make query`), a 30-day logs artifact, and the Pages site |

The cache is best effort: GitHub evicts entries unused for 7 days, and a
missed week means the next night starts from an empty warehouse (the raw tables
reload; `star_growth` history restarts). If that matters, add a step that
pushes `warehouse.duckdb` somewhere durable.

"Run workflow" in the Actions tab takes two inputs: `fixture` (use inline
data, no API calls) and `date` (run as a past night, like `BULLWHIP_DATE`).

`scripts/build_site.sh` is what assembles the Pages site (`web/` plus the
project's `logs/`); run it locally to see exactly what gets published.

## Step 8: Query via MCP (not yet exercised)

`mcp/` contains a TypeScript stdio MCP server with six read-only tools
(`night_status`, `night_stats`, `list_targets`, `night_summary`, `get_target_log`,
`explain_critical_path`) that read the same artifacts as the dashboards. It has
not been built or run against this example yet; treat it as a sketch until it
has.

`night_status` mirrors `logs/<date>/status.json` and adds heartbeat age and
liveness. `night_stats` mirrors `logs/<date>/ledger.json`. `night_summary`
combines execution timing with the headline ledger statistics.

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

## How it works

### The data flow

```
GitHub API (or fixture)
    │
    ▼
dlt-ops pipeline run          ← assertions, quarantine, runs ledger
    │
    ├─ repos_metadata table   ← stars, forks, issues, topics
    ├─ contributors table     ← login, contributions per repo
    ├─ releases table         ← tag_name, published_at
    └─ star_snapshots table   ← daily star count (append)
    │
    ▼
sqlmesh plan --auto-apply     ← transforms (physical tables in sqlmesh__my_db,
    │                            views in my_db pointing at them)
    ├─ github_repos    FULL                       ← staging with derived columns
    ├─ github_health   FULL                       ← bus factor, health_status, latest release
    └─ star_growth     INCREMENTAL_BY_UNIQUE_KEY  ← daily delta, weekly growth %
    │
    ▼
DuckDB warehouse.duckdb       ← one file: raw tables, models, and two of the ledgers
```

### The ledgers

| Ledger | What it answers | Where |
|---|---|---|
| `timing_env.log` | What ran at 3am and how long | `logs/<date>/timing_env.log` |
| dlt-ops runs | Records extracted/loaded per run, errors | `warehouse.duckdb` `my_db._dlt_ops_runs` |
| SQLMesh state | Which snapshots/intervals are current | `warehouse.duckdb` schema `sqlmesh` |
| `ledger.json` | Tonight's slice of the two above, next to the make logs | `logs/<date>/ledger.json` (from `lib/run_ledger.py`) |

The dashboards read only the `logs/<date>/` files; they never open the
warehouse. That is what `ledger.json` is for.

### The Mara organs

Three things make can't express, adopted at the make layer:

1. **Critical-path priority** — `lib/critical_path.py` parses the make DAG
   (`make -pnr`), sums each target's recipe time per night from `timing_env.log`,
   and orders long chains first using `.WAIT` waves (gmake 4.4+). Its `dag.json`
   is what the dashboards draw.

2. **Content-hash cache keys** — `lib/fingerprint.py` SHA-256s the recipe +
   content deps so re-running with edited logic doesn't no-op against yesterday's
   marker. (Available in `boilerplate.mk`; this example does not use it yet.)

3. **The outcome record** — `lib/run_ledger.py`: a green marker proves a command
   exited 0, not that rows arrived. After make, it snapshots the dlt-ops runs
   ledger and the warehouse row counts into `ledger.json`, so dashboard C can
   put "make exit 0" and "21 records loaded" on the same line.

## Next steps

- Check what yesterday's trending list looked like: query `my_db.trending_repos`
  for a different `snapshot_date`
- Add Slack notifications: set `BULLWHIP_NOTIFY=slack` and `SLACK_WEBHOOK_URL`
- Browse the dashboards: `python -m http.server 8765 -d .` → `http://localhost:8765/web/`
- Build the MCP server: `cd mcp && npm install && npm run build`
- Run the test suite: `python -m pytest tests/ -v`
