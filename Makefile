# DNHacks_app — root orchestration.
# Targets no-op gracefully when a component hasn't picked a stack yet.

.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPONENTS := hardware/m5stack-node hardware/pi-server hardware/laptop-server ml services/api web

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

.PHONY: risk
risk: ## Rebuild web/data/risk.json — plant-level 12-month disruption risk
	@python3 -m ml.risk.emit

.PHONY: risk-train
risk-train: ## Re-run the model comparison across three cutoffs (~40s)
	@python3 -m ml.risk.train

.PHONY: risk-check
risk-check: ## Assert the shipping bar: beats both baselines, calibrated
	@python3 -m ml.risk.train --selftest
	@python3 -m ml.risk.calibrate

.PHONY: depot-demo
depot-demo: ## Replay 24h of storage history into a running API (no hardware needed)
	@# DEPOT_TRUST_DEVICE_TS is read by the SERVER, not by this client. It lives in
	@# .env so `make dev` picks it up. Without it the API stamps every replayed
	@# sample with receipt time and the 24h window collapses to a few seconds.
	@curl -sf $${API:-http://localhost:8000}/health >/dev/null \
	  || { echo "API not up — run 'make dev' first"; exit 1; }
	@# Reset first. A bin that still holds the previous run's history computes its
	@# MKT over a window that mixes the two, and the breach silently fails to latch
	@# — it reports `ok` at 25.9 C against a 25.0 C ceiling. Do not remove this.
	@curl -sf -X POST $${API:-http://localhost:8000}/depot/nodes/$${NODE:-sns-depot-01-bin-a}/reset >/dev/null || true
	@./hardware/m5stack-node/replay.py --api $${API:-http://localhost:8000} \
	  synth --scenario $${SCENARIO:-breach}

.PHONY: sites
sites: ## Resolve API-tier DMF holders through DECRS and geocode every plant -> web/data/{nodes,edges}.sites.json, geo.json
	@python3 ml/sites.py

.PHONY: aegis
aegis: ## Re-score every API's and precursor's DMF holders -> web/data/reroute.json (run `make sites` first)
	@python3 ml/aegis.py --write

.PHONY: status
status: ## What actually exists in this repo right now
	@for c in $(COMPONENTS); do \
	  n=$$(find $$c -type f -not -name 'README.md' -not -name '.gitkeep' 2>/dev/null | wc -l); \
	  printf "  %-26s %s files\n" "$$c" "$$n"; \
	done
