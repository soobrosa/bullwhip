# incremental_load — the canonical pattern, modernized.
#
# Old: dump to CSV → cp to /tmp → hand-rolled loader SQL (3 make targets, 3 ERB templates)
# New: dlt-ops ingests from source → SQLMesh transforms in the warehouse (2 make targets)
#
# dlt-ops owns: pre-load assertions, runs ledger, checkpoints, backfill,
# schema-drift reconciliation, import sandbox, pipeline validate.
# The make target is just "did tonight's run finish."

include ../../lib/boilerplate.mk

# The boilerplate points SHELL at ./lib/tracking_shell.py, but this makefile
# lives under examples/incremental_load/, so re-point it at the project lib.
# Use a recursive assignment (=, not :=) so $@ expands per-recipe to the
# target name and the tracking shell records it in timing_env.log.
SHELL = ../../lib/tracking_shell.py --target $@ --date $(TODAY)

scaffold:: intermediate/$(TODAY)/

intermediate/$(TODAY)/:
	mkdir -p $@

# Validate the dlt-ops project before anything runs.
# 21 static rules: naming, config, schema contracts, import safety.
# Re-checked at runtime on every run.
intermediate/$(TODAY)/validate.done: | intermediate/$(TODAY)/
	cd ../.. && dlt-ops pipeline validate --strict
	@touch $@

# Ingest: dlt-ops runs the pipeline with pre-load assertions,
# writes to the _dlt_ops_runs ledger, and commits atomically.
# The marker file lands only after dlt-ops commits.
intermediate/$(TODAY)/ingest.done: intermediate/$(TODAY)/validate.done | intermediate/$(TODAY)/
	cd ../.. && dlt-ops pipeline run -s people_ingest -y
	@touch $@

# Reconcile: detect schema drift after ingestion.
# Additive (new columns) + removal (columns that went dark) if configured.
intermediate/$(TODAY)/reconcile.done: intermediate/$(TODAY)/ingest.done | intermediate/$(TODAY)/
	cd ../.. && dlt-ops pipeline reconcile --all --include-removal
	@touch $@

# Transform: SQLMesh runs the models that depend on the ingested table.
# cron only ever runs `sqlmesh run`, never `plan`.  Plans deploy from laptop/CI.
intermediate/$(TODAY)/sqlmesh.done: intermediate/$(TODAY)/reconcile.done
	cd ../../sqlmesh && sqlmesh --gateway prod run
	@touch $@

# The full pipeline target.
imports: scaffold intermediate/$(TODAY)/sqlmesh.done

# Status: read the _dlt_ops_runs ledger.
status:
	cd ../.. && dlt-ops pipeline status --limit 10

# Backfill: re-run the pipeline for a past window.
# Usage: make backfill FROM=2024-01-01T00:00:00Z TO=2025-01-01T00:00:00Z CHUNK=7d
backfill:
	cd ../.. && dlt-ops pipeline backfill people_ingest --from $(FROM) --to $(TO) --chunk $(CHUNK)

# Exports / notifications run after transforms.
exports: intermediate/$(TODAY)/sqlmesh.done
	@echo "[exports] nothing to export yet"

backup::
	@echo "[backup] nothing to back up yet"
