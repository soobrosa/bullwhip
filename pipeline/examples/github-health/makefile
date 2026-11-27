# github-health — track GitHub repos' stars, growth, and health.
#
# This is the primary example and tutorial.  It runs end-to-end with
# fixture data (no GitHub token needed) or against the real API.
#
# Fixture mode (no network, no token):
#   GITHUB_HEALTH_FIXTURE=1 make imports
#
# Real mode (needs a GitHub token in .dlt/secrets.toml):
#   make imports

include ../../../pipeline/lib/boilerplate.mk

# The boilerplate points SHELL at pipeline/lib/tracking_shell.py, but this
# makefile lives under pipeline/examples/github-health/, so re-point it at
# the project lib.  Use a recursive assignment (=, not :=) so $@ expands
# per-recipe to the target name and the tracking shell records it in
# timing_env.log.
SHELL = ../../../pipeline/lib/tracking_shell.py --target $@ --date $(TODAY)

# The warehouse is ephemeral: pipeline/data/*.parquet is the durable copy
# (committed
# to the repo), warehouse.duckdb is gitignored and rebuilt whenever missing —
# fresh clone, evicted Actions cache, wiped container.  Re-ingestion after a
# restore is idempotent (the sources merge on primary keys); SQLMesh then
# re-materialises its models from the restored tables.
# Defined BEFORE any rule that uses it: prerequisite lists are expanded when
# the line is read, not lazily.
DUCKDB = $(if $(BULLWHIP_DUCKDB),$(BULLWHIP_DUCKDB),../../../warehouse.duckdb)
DATA_DIR = ../../../pipeline/data

# Rebuild ONLY when the file is missing.  Deliberately no prerequisites:
# pipeline/data/*.parquet is exported FROM this warehouse nightly, so its
# mtime must never trigger a rebuild (that would cascade re-ingest every
# night).
$(DUCKDB):
	python ../../../pipeline/lib/warehouse_parquet.py restore --duckdb "$@" --data-dir "$(DATA_DIR)"
	@touch "$@"

.PHONY: restore
restore: $(DUCKDB)

scaffold:: intermediate/$(TODAY)/

intermediate/$(TODAY)/:
	mkdir -p $@

# Validate the dlt-ops project before anything runs.  The warehouse is an
# ORDER-ONLY prerequisite: it must exist (restored from pipeline/data/*.parquet if
# missing) before anything opens it, but it must never mark these targets
# stale — ingest and sqlmesh write to it, so a normal prerequisite would be
# newer than these markers forever and re-run the whole chain every time.
intermediate/$(TODAY)/validate.done: | intermediate/$(TODAY)/ $(DUCKDB)
	cd ../../.. && dlt-ops pipeline validate --strict
	@touch $@

# Ingest: dlt-ops pulls repo metadata, contributors, releases, star snapshots.
# In fixture mode, GITHUB_HEALTH_FIXTURE=1 returns inline data.
intermediate/$(TODAY)/ingest.done: intermediate/$(TODAY)/validate.done | intermediate/$(TODAY)/ $(DUCKDB)
	cd ../../.. && dlt-ops pipeline run -s github_health -y
	@touch $@

# Reconcile: detect schema drift after ingestion.
intermediate/$(TODAY)/reconcile.done: intermediate/$(TODAY)/ingest.done | intermediate/$(TODAY)/
	cd ../../.. && dlt-ops pipeline reconcile --all --include-removal
	@touch $@

# Transform: SQLMesh applies the health models to the warehouse.
# `plan --auto-apply` bootstraps the prod environment on a fresh warehouse and
# is a no-op when nothing has changed; `run` then evaluates whichever models
# have a completed daily interval.  Both exit 0 when there is nothing to do.
# Two nights on the same calendar day therefore refresh the raw tables but not
# the models: the second `run` reports "No models are ready to run".
intermediate/$(TODAY)/sqlmesh.done: intermediate/$(TODAY)/reconcile.done
	cd ../../../pipeline/sqlmesh && sqlmesh --gateway prod plan --no-prompts --auto-apply && sqlmesh --gateway prod run
	@touch $@

# The full pipeline.
imports: scaffold intermediate/$(TODAY)/sqlmesh.done

# Query the results.
query: intermediate/$(TODAY)/sqlmesh.done
	@python query.py

# Status: read the dlt-ops runs ledger.
status:
	cd ../../.. && dlt-ops pipeline status --limit 10

# Backfill: re-run for a past window.
backfill:
	cd ../../.. && dlt-ops pipeline backfill github_health --from $(FROM) --to $(TO) --chunk $(CHUNK)

# Clean up for dev.  Deletes the ephemeral warehouse and dlt's local pipeline
# state — deliberately NOT pipeline/data/, the durable Parquet copy.
nuke::
	rm -f intermediate/$(TODAY)/*.done
	rm -f ../../../warehouse.duckdb
	rm -rf ~/.dlt/pipelines/github_health_pipeline

# Backup = persist the raw tables as Parquet under pipeline/data/ — the
# durable copy
# of the data (the DuckDB file itself is never persisted).  Content-hash
# gated on the warehouse file (Mara organ 2): a retry within the same night,
# or a re-run with nothing changed, skips the export.  --check exits 0
# (unchanged, marker refreshed) or 1 (changed), so the check and the work
# share one shell via `|| { ... }`.
BACKUP_RECIPE = "export my_db tables to pipeline/data/*.parquet"

backup:: intermediate/$(TODAY)/sqlmesh.done
	@python ../../../pipeline/lib/fingerprint.py --check --target $@ \
		--recipe $(BACKUP_RECIPE) --deps "$(DUCKDB)" \
	|| { \
		python ../../../pipeline/lib/warehouse_parquet.py export --duckdb "$(DUCKDB)" --data-dir "$(DATA_DIR)"; \
		python ../../../pipeline/lib/fingerprint.py --write --target $@ \
			--recipe $(BACKUP_RECIPE) --deps "$(DUCKDB)"; \
	}
