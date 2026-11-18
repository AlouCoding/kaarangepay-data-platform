.PHONY: help up down reset logs test test-java test-python backfill live integrity psql

help:            ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:              ## Build and start Postgres + payment-core
	docker compose up -d --build postgres payment-core

down:            ## Stop everything (keeps data)
	docker compose --profile traffic down

reset:           ## Stop everything and DELETE the database volume
	docker compose --profile traffic down -v

logs:            ## Follow payment-core logs
	docker compose logs -f payment-core

test: test-java test-python  ## Run all tests

test-java:       ## Unit + integration tests (needs Docker for Testcontainers)
	cd payment-core && mvn -B verify

test-python:     ## Lint, type-check and test the generator
	cd traffic-generator && ruff check src tests && mypy src && pytest -q

backfill:        ## Generate 30 days of history (Nov 2026) with simulated event times
	mkdir -p data
	docker compose --profile traffic run --rm traffic-generator \
		--base-url http://payment-core:8080 --rate 300 backfill --start 2026-11-01 --days 30

live:            ## Start continuous real-time traffic in the background
	docker compose --profile traffic up -d traffic-generator

integrity:       ## Check the three ledger invariants
	@curl -s http://localhost:$${APP_PORT:-8080}/api/v1/ledger/integrity; echo

psql:            ## Open a SQL shell on the database
	docker compose exec postgres psql -U mmplatform -d mmplatform
