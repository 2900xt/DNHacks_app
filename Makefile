# DNHacks_app — root orchestration.
# Targets no-op gracefully when a component hasn't picked a stack yet.

.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPONENTS := firmware ml services/api web

.PHONY: help
help: ## Show this help
	@echo "DNHacks_app — targets:"
	@grep -hE '^[a-zA-Z_/-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Components: $(COMPONENTS)"

.PHONY: bootstrap
bootstrap: ## Install dependencies for every component that has a bootstrap
	@./scripts/bootstrap.sh

.PHONY: dev
dev: ## Run every component that defines a dev target (parallel)
	@./scripts/dev.sh

.PHONY: check
check: ## Cheap sanity pass: contracts parse, env keys present
	@./scripts/check.sh

.PHONY: demo
demo: ## Bring up exactly what the demo path needs. Edit me once the path is locked.
	@echo "TODO: wire this to the demo path in ../DNHacks_brain/strategy/DEMO_PATH.md"
	@$(MAKE) dev

.PHONY: status
status: ## What actually exists in this repo right now
	@for c in $(COMPONENTS); do \
	  n=$$(find $$c -type f -not -name 'README.md' -not -name '.gitkeep' 2>/dev/null | wc -l); \
	  printf "  %-14s %s files\n" "$$c" "$$n"; \
	done
