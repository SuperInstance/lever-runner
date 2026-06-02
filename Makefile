# Lever-Runner — common developer commands
#
# Usage:
#   make help         # show this file
#   make install      # editable install into .venv
#   make seed         # (re)build the LanceDB table with the seed pack
#   make smoke        # run the 18-check end-to-end test (isolated tempdir)
#   make bench        # run the 20-task benchmark
#   make bot          # start the Telegram bot in the foreground
#   make promote      # run the hourly self-improvement loop once
#   make export       # dump the current table to JSONL on stdout
#   make status       # show table size + recent activity
#   make test         # run pytest (only smoke.py today; expands as tests grow)
#   make lint         # ruff check + ruff format --check
#   make clean        # remove caches, sandbox, generated snapshots
#   make release      # tag vX.Y.Z and push to origin (requires clean tree)

SHELL := /bin/bash
PY := .venv/bin/python
PIP := .venv/bin/pip

# Disable the implicit "rule" that would try to make a file called "status",
# "test", "smoke", etc. from a same-named source. We're using them as
# phony targets, not file targets.
.PHONY: help install seed smoke bench bot promote export status test lint clean release all install-pack web

all: help

help: ## show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nLever-Runner developer commands\n\n"} \
	     /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo

install: ## editable install into .venv
	$(PIP) install -e ".[dev]"

install-pack: ## install a community skill pack (set PACK=name, e.g. PACK=k8s-ops)
	@if [ -z "$(PACK)" ]; then echo "PACK is required, e.g. make install-pack PACK=k8s-ops"; exit 1; fi
	@if [ ! -f "community/$(PACK).jsonl" ]; then echo "no such pack: community/$(PACK).jsonl"; exit 1; fi
	$(PY) -m lever_runner.seed_import community/$(PACK).jsonl

seed: ## (re)build the LanceDB table from init_db.py
	$(PY) init_db.py --reset

web: ## serve web/index.html on :8080 (Ctrl-C to stop)
	cd web && $(PY) -m http.server 8080

smoke: ## 18-check end-to-end test, isolated tempdir, exit 0/1
	$(PY) -m tests.smoke

bench: ## 20-task benchmark; forces LLM_BACKEND=passthrough
	$(PY) -m lever_runner.benchmark

bot: ## start the Telegram bot in the foreground
	$(PY) -m lever_runner.bot

promote: ## run the hourly self-improvement loop once
	$(PY) -m lever_runner.auto_promote

export: ## dump the current table to JSONL on stdout
	$(PY) -m lever_runner.seed_export --include-stats

status: ## show table size + recent activity
	$(PY) -m lever_runner status

test: smoke ## alias for smoke (no pytest tests yet)

lint: ## ruff check + format --check
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

clean: ## remove caches, sandbox, generated snapshots
	rm -rf src/lever_runner/__pycache__ tests/__pycache__ .pytest_cache
	rm -rf logs/embed_usage.jsonl logs/token_usage.jsonl
	rm -rf /tmp/lever-runner
	@echo "cleaned. (live LanceDB table at data/lever.lancedb NOT touched)"

release: ## tag vX.Y.Z (set VERSION=...) and push to origin
	@if [ -z "$(VERSION)" ]; then echo "VERSION is required, e.g. make release VERSION=0.1.1"; exit 1; fi
	@if [ -n "$$(git status --porcelain)" ]; then echo "working tree is dirty; commit first"; exit 1; fi
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin main
	git push origin v$(VERSION)
	gh release create v$(VERSION) --title "v$(VERSION)" --generate-notes
