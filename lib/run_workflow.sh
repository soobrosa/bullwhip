#!/bin/bash
# run_workflow.sh — the cron entry point.
#
# Guards itself (locked file + ps check for concurrent runs), counts existing
# attempt logs, runs make with the configured targets, and on the final
# attempt either reports success or cats all logs so cron emails them.
#
# Writes logs/<date>/status.json at the top of each loop so the live UI can
# distinguish "night finished" from "scheduler dead".

set -o pipefail

cd "$(dirname "$0")/.."

export PATH="$PATH:/usr/local/bin/"

BULLWHIP_ROOT="$(pwd)"
export BULLWHIP_ROOT

# Source configuration if it exists.
if [ -f config/bullwhip.sh ]; then
    source config/bullwhip.sh
fi

# The makefile to drive may live outside the repo root (e.g. an example);
# logs/ and locked are relative to wherever make runs.
if [ -n "$BULLWHIP_PROJECT_DIR" ]; then
    cd "$BULLWHIP_PROJECT_DIR" || exit 1
fi

# Defaults if not set.
BULLWHIP_MAX_ATTEMPTS="${BULLWHIP_MAX_ATTEMPTS:-23}"
BULLWHIP_PARALLEL_JOBS="${BULLWHIP_PARALLEL_JOBS:-6}"
BULLWHIP_TARGETS="${BULLWHIP_TARGETS:-scaffold}"
BULLWHIP_FAILURE_TARGETS="${BULLWHIP_FAILURE_TARGETS:-backup}"
BULLWHIP_NOTIFY="${BULLWHIP_NOTIFY:-none}"
BULLWHIP_LIVE_UI="${BULLWHIP_LIVE_UI:-0}"
# Under cron a failed non-final attempt exits 0 and waits for the next tick.
# A runner that loops in-process (GitHub Actions) sets this to 1 to get a
# non-zero exit it can retry on.
BULLWHIP_FAIL_FAST="${BULLWHIP_FAIL_FAST:-0}"

# Single-flight: skip if a lock file exists.
if [ -f locked ]; then
    exit 0
fi

# BULLWHIP_DATE lets a rerun (backfill, test) target another night; make
# picks the same date up through TODAY so markers and logs line up.
DATE="${BULLWHIP_DATE:-$(date +"%Y-%m-%d")}"
export TODAY="$DATE"
mkdir -p "logs/${DATE}"

# Count existing attempts.
ATTEMPT_COUNT=$(ls -1H "logs/${DATE}/attempt-"*.log 2>/dev/null | wc -l | sed 's/ *$//;s/^ *//')
if [ "$ATTEMPT_COUNT" -gt "$BULLWHIP_MAX_ATTEMPTS" ]; then
    exit 0
fi

export ATTEMPT_COUNT

THIS_ATTEMPT=$(printf "logs/${DATE}/attempt-%02d.log" "$ATTEMPT_COUNT")
echo -e "\n\n[+] Starting attempt No ${ATTEMPT_COUNT} with PID $$..." >> "$THIS_ATTEMPT"
date >> "$THIS_ATTEMPT"

# Write status.json heartbeat — the live UI reads this.
write_status() {
    # -1 = make has not finished yet (the UI treats it as "running").
    local exit_code="${1:--1}"
    local status="running"
    if [ "$ATTEMPT_COUNT" -ge "$BULLWHIP_MAX_ATTEMPTS" ]; then
        status="final"
    fi
    python3 -c "
import json, os, datetime
status = {
    'attempt': $ATTEMPT_COUNT,
    'max_attempts': $BULLWHIP_MAX_ATTEMPTS,
    'pid': $$,
    'started_at': datetime.datetime.now().isoformat(),
    'make_exit': $exit_code,
    'status': '$status',
    'heartbeat': datetime.datetime.now().isoformat(),
}
with open('logs/${DATE}/status.json', 'w') as f:
    json.dump(status, f, indent=2)
" 2>/dev/null
}

write_status ""

# Prevent overlapping runs.  Ignore our own ancestor chain (cron, the shell
# that launched us) so a wrapper whose command line mentions this script does
# not count as a concurrent run.
ANCESTORS=" $$ "
_p=$PPID
while [ -n "$_p" ] && [ "$_p" -gt 1 ] 2>/dev/null; do
    ANCESTORS="$ANCESTORS$_p "
    _p=$(ps -o ppid= -p "$_p" 2>/dev/null | tr -d ' ')
done
if ps -eo pid,command | awk -v skip="$ANCESTORS" 'index(skip, " " $1 " ") == 0' \
        | egrep '^ *[0-9]+ +(/[^ ]*/)?bash( -[a-z]+)* +[^ -][^ ]*[r]un_workflow\.sh( |$)' >> "$THIS_ATTEMPT" 2>&1; then
    echo "[!] Detected other run_workflow.sh still in progress: Aborting" >> "$THIS_ATTEMPT"

    if [ "$ATTEMPT_COUNT" -ge "$BULLWHIP_MAX_ATTEMPTS" ]; then
        echo "[!] Max attempts ($BULLWHIP_MAX_ATTEMPTS) reached but processing is still running!"
        exit 1
    else
        exit 0
    fi
fi

# Optionally start the live UI server.  Served from the repo root so web/ and
# the project's logs/ are both reachable; the dashboards take
# ?project=<dir>&date=<date> to find tonight's files.
if [ "$BULLWHIP_LIVE_UI" = "1" ] && ! lsof -i :8765 >/dev/null 2>&1; then
    python3 -m http.server 8765 -d "$BULLWHIP_ROOT" >/dev/null 2>&1 &
    LIVE_UI_PID=$!
    trap "kill $LIVE_UI_PID 2>/dev/null" EXIT
fi

NIGHT_STARTED_AT=$(date +"%Y-%m-%dT%H:%M:%S%z")

# Run the main targets, then failure targets.
MAKE_EXIT_CODES=0
for TARGET in "-k -j $BULLWHIP_PARALLEL_JOBS $BULLWHIP_TARGETS" $BULLWHIP_FAILURE_TARGETS; do
    echo -e "\n\n[+] Working on target ${TARGET}" >> "$THIS_ATTEMPT"
    make ${TARGET} >> "$THIS_ATTEMPT" 2>&1
    LAST_EXIT_CODE=$?
    MAKE_EXIT_CODES=$((LAST_EXIT_CODE + MAKE_EXIT_CODES))
    echo -e "\n\n[+] Completed ${TARGET}" >> "$THIS_ATTEMPT"
    date >> "$THIS_ATTEMPT"
done

# Update heartbeat with exit code.
write_status "$MAKE_EXIT_CODES"

# Outcome record: what the data layer says happened tonight (best effort).
python3 "$BULLWHIP_ROOT/lib/run_ledger.py" --root "$BULLWHIP_ROOT" \
    --since "$NIGHT_STARTED_AT" --out "logs/${DATE}/ledger.json" \
    ${BULLWHIP_DUCKDB:+--duckdb "$BULLWHIP_DUCKDB"} \
    ${BULLWHIP_DATASET:+--dataset "$BULLWHIP_DATASET"} >> "$THIS_ATTEMPT" 2>&1 || true

# Refresh the DAG with tonight's timings so the UI's critical path is current.
# Scoped to the targets the night runs (plus cleanup) so dag.json doesn't
# include helper targets make never touches.
python3 "$BULLWHIP_ROOT/lib/critical_path.py" --makefile-dir . --log-dir logs \
    --targets "$BULLWHIP_TARGETS $BULLWHIP_FAILURE_TARGETS cleanup" \
    --dag-output "logs/${DATE}/dag.json" >> "$THIS_ATTEMPT" 2>&1 || true

# Night index for the dashboards' picker: static hosts (GitHub Pages) have no
# directory listing, so write one.
ls -1 logs | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -r \
    | python3 -c "import json,sys; json.dump([l.strip() for l in sys.stdin if l.strip()], open('logs/index.json','w'))" 2>/dev/null || true

# If no errors or this is the last attempt: clean up.
if [ "$MAKE_EXIT_CODES" -eq 0 ] || [ "$ATTEMPT_COUNT" -ge "$BULLWHIP_MAX_ATTEMPTS" ]; then
    make cleanup >> "$THIS_ATTEMPT" 2>&1
    LAST_EXIT_CODE=$?
    MAKE_EXIT_CODES=$((LAST_EXIT_CODE + MAKE_EXIT_CODES))
    write_status "$MAKE_EXIT_CODES"
fi

# Final attempt handling.
if [ "$ATTEMPT_COUNT" -ge "$BULLWHIP_MAX_ATTEMPTS" ]; then
    if [ "$MAKE_EXIT_CODES" -gt 0 ]; then
        echo "[!] Final exit code was $MAKE_EXIT_CODES, here are all the logs:"
        cat "logs/${DATE}/attempt-"*.log

        # Slack notification on final failure.
        if [ "$BULLWHIP_NOTIFY" = "slack" ] || [ "$BULLWHIP_NOTIFY" = "slack,email" ]; then
            python3 "$BULLWHIP_ROOT/lib/notify_slack.py" --date "$DATE" --exit-code "$MAKE_EXIT_CODES" \
                --webhook "$SLACK_WEBHOOK_URL" 2>/dev/null || true
        fi

        exit 1
    fi

    # Test attempt log sizes.
    python3 "$BULLWHIP_ROOT/tests/attempt_log_sizes.py"
    if [ $? -gt 0 ]; then
        ls -l "logs/${DATE}/"
        exit 1
    fi

    echo "Everything is ok."

    # Slack morning digest on success.
    if [ "$BULLWHIP_NOTIFY" = "slack" ] || [ "$BULLWHIP_NOTIFY" = "slack,email" ]; then
        python3 "$BULLWHIP_ROOT/lib/notify_slack.py" --date "$DATE" --digest --webhook "$SLACK_WEBHOOK_URL" 2>/dev/null || true
    fi

    # Mark the night as finished.
    python3 -c "
import json, datetime
path = 'logs/${DATE}/status.json'
try:
    with open(path) as f:
        status = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    status = {}
status.update({'status': 'finished', 'finished_at': datetime.datetime.now().isoformat()})
with open(path, 'w') as f:
    json.dump(status, f, indent=2)
" 2>/dev/null

    exit 0
else
    # Silently ignore error and retry in 30 minutes.
    if [ "$BULLWHIP_FAIL_FAST" = "1" ] && [ "$MAKE_EXIT_CODES" -gt 0 ]; then
        exit 1
    fi
    exit 0
fi
