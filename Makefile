# HippoCampy Daemon — Makefile

.PHONY: help install rebuild-venv test mcpb clean check-cypher check-principal check-plan-pointers check-env-drift

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install dependencies (dev mode)
	pip3 install -e ".[dev]" --break-system-packages 2>/dev/null \
		|| pip install -e ".[dev]"
	python3 -m spacy download en_core_web_md 2>/dev/null || true

rebuild-venv: ## B416: rebuild .venv from scratch (fixes local environment drift, e.g. a stale torch)
	rm -rf .venv
	python3.12 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	.venv/bin/pip install -e ".[test]"
	.venv/bin/python -m spacy download en_core_web_md
	@echo ""
	@echo "Rebuilt .venv. Verifying it's clean:"
	.venv/bin/python scripts/check_env_drift.py

test: ## Run the full test suite
	python3 -m pytest tests/ -v

test-adapters: ## Run adapter tests only
	python3 -m pytest tests/test_adapters.py -v

check-cypher: ## B314 ratchet: fail if inline Cypher outside the allowlist increased
	python3 scripts/check_cypher_ratchet.py

check-principal: ## B315 ratchet: fail if handlers not declaring `principal` increases
	python3 scripts/check_principal_ratchet.py

check-plan-pointers: ## Fail if a backlog card's Plan: header names a missing plans/*.md file
	python3 scripts/check_backlog_plan_pointers.py

check-env-drift: ## B416: report local .venv drift from declared dependencies (NOT run in CI -- see backlog/B416.md)
	python3 scripts/check_env_drift.py

mcpb: ## Build .mcpb bundle for Claude Desktop
	@echo "Building hippocampy.mcpb..."
	@cd $(CURDIR) && zip -r hippocampy.mcpb \
		mcpb/manifest.json \
		mcpb/install.sh \
		mcpb/uninstall.sh \
		adapters/ \
		mcp_engine/ \
		web/ \
		sidequests/ \
		brain_daemon.py \
		requirements.txt \
		sidequests.toml \
		InvertorsDocs/GistSeedExamples.md \
		-x '*.pyc' -x '*/__pycache__/*' -x '.git/*' -x 'tests/*' -x '*.db' \
		-x '*.mcpb'
	@echo "Built: hippocampy.mcpb"
	@ls -lh hippocampy.mcpb

clean: ## Remove build artifacts
	rm -rf hippocampy.mcpb dist/ build/ *.egg-info
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
