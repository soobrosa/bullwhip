# bullwhip boilerplate — included by user Makefiles.
# Provides dated-target helpers, the tracking shell, and extensible targets.

ifndef TODAY
  TODAY := $(shell date +%Y-%m-%d)
endif

TMP_TOKEN := $(shell date +%H%M%S)

# Platform-aware YESTERDAY (Mac date vs GNU date)
ifeq ($(shell uname -s),Darwin)
  YESTERDAY := $(shell date -v-1d +%Y-%m-%d)
  YESTERDAY_SLASHED := $(shell date -v-1d +%Y/%m/%d)
else
  YESTERDAY := $(shell date --date="1 day ago" +%Y-%m-%d)
  YESTERDAY_SLASHED := $(shell date --date="1 day ago" +%Y/%m/%d)
endif

# Unique suffix so parallel make jobs don't clobber each other's temp files.
TMP_OUT = $@.$(TMP_TOKEN).tmp

# The tracking shell wraps every recipe command for logging + timing.
# Default assumes make runs from the repo root; example makefiles under
# pipeline/examples/*/ override this with their own relative path.
SHELL := pipeline/lib/tracking_shell.py --target $@ --date $(TODAY)

.PHONY: all nuke scaffold backup clean-test cleanup list-all-targets

# Default — do nothing unless a target is specified.
all:
	@echo Specify target

# Scaffold the directory structure for today (redefine in your Makefile).
scaffold:: logs/$(TODAY)/

# Log directory.
logs/$(TODAY)/:
	mkdir -p $@

# Clean up — WARNING: use nuke only during development!
nuke::

# Cleanup terminates any pending resources (redefine in your Makefile).
cleanup::

# Clean up test folders.
clean-test::
	@rm -rf logs/_test_
	@mkdir -p logs/_test_

# List all available targets from the makefile.
list-all-targets:
	@egrep -h '^[a-zA-Z][^# :=]+:([^=]|$$)' Makefile *.mk | cut -d: -f1 | sed -e 's/$$(TODAY)/'$(TODAY)'/g'

# Backup after target execution is finished (redefine in your Makefile).
# WARNING: This must be the last target in the dependency list!
backup::

# --- fingerprint marker convention ---
# Content-hash gating for targets whose inputs aren't file-mtimes (exports,
# backups, notifications).  pipeline/lib/fingerprint.py --check exits 0 (and
# refreshes
# the marker) when recipe+deps are unchanged, 1 when they changed, so the
# check and the real work must share one shell (`|| { ... }`) — make runs
# each recipe line in its own shell and a bare `exit 0` cannot skip the rest:
#   target:
#   	@python pipeline/lib/fingerprint.py --check --target $@ \
#   		--recipe "the command" --deps "a.py b.sql" \
#   	|| { \
#   		the actual recipe; \
#   		python pipeline/lib/fingerprint.py --write --target $@ \
#   			--recipe "the command" --deps "a.py b.sql"; \
#   	}
# See pipeline/lib/fingerprint.py for details.
