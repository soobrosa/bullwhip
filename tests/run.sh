#!/bin/bash
# tests/run.sh — master test runner.
#
# Runs the Python test suite and the makefile hygiene checks.

set -e

cd "$(dirname "$0")/.."

# Python unit tests.
python -m pytest tests/ -v
pytest_exit=$?

# Makefile hygiene: verify the example makefile parses.
if [ -f pipeline/examples/incremental_load/makefile ]; then
    cd pipeline/examples/incremental_load
    make -n imports SHELL=/bin/bash >/dev/null 2>&1
    make_parse_exit=$?
    cd ../../..
else
    make_parse_exit=0
fi

# Critical path DAG generation (if make is available).
if command -v make &>/dev/null; then
    python pipeline/lib/critical_path.py --makefile-dir . --dag-output /tmp/test_dag.json --print-waves 2>/dev/null || true
fi

exit $((pytest_exit + make_parse_exit))
