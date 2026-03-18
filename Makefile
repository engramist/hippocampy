# SideQuests Brain Daemon — Makefile

.PHONY: help install test mcpb clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install dependencies (dev mode)
	pip3 install -e ".[dev]" --break-system-packages 2>/dev/null \
		|| pip install -e ".[dev]"
	python3 -m spacy download en_core_web_md 2>/dev/null || true

test: ## Run the full test suite
	python3 -m pytest tests/ -v

test-adapters: ## Run adapter tests only
	python3 -m pytest tests/test_adapters.py -v

mcpb: ## Build .mcpb bundle for Claude Desktop
	@echo "Building sidequests-brain.mcpb..."
	@cd $(CURDIR) && zip -r sidequests-brain.mcpb \
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
	@echo "Built: sidequests-brain.mcpb"
	@ls -lh sidequests-brain.mcpb

clean: ## Remove build artifacts
	rm -rf sidequests-brain.mcpb dist/ build/ *.egg-info
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
