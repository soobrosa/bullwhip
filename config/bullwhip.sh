# bullwhip configuration — sourced by run_workflow.sh.
# Drives the github-health example on fixture data.

export BULLWHIP_PROJECT_DIR="examples/github-health"
export BULLWHIP_TARGETS="imports"
export BULLWHIP_FAILURE_TARGETS="backup"
export BULLWHIP_PARALLEL_JOBS=4
# A runner that retries in-process (GitHub Actions) sets this lower.
export BULLWHIP_MAX_ATTEMPTS="${BULLWHIP_MAX_ATTEMPTS:-3}"
export BULLWHIP_NOTIFY="none"
export BULLWHIP_LIVE_UI=0

# The warehouse: SQLMesh's gateway and the outcome ledger both read this.
# Overridable so a container can point it at a mounted volume.
export BULLWHIP_DUCKDB="${BULLWHIP_DUCKDB:-$BULLWHIP_ROOT/warehouse.duckdb}"
export BULLWHIP_DATASET="my_db"

# Example-specific: 1 = inline fixture data, no GitHub token needed.
# The GitHub Action exports 0 to hit the real API with its GITHUB_TOKEN.
export GITHUB_HEALTH_FIXTURE="${GITHUB_HEALTH_FIXTURE:-1}"
