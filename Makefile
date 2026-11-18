.PHONY: help up down reset logs test test-java test-python backfill live integrity psql cdc-up cdc-status cdc-topics cdc-down bronze-up bronze-reconcile silver fraud fraud-eval

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

test-python:     ## Lint, type-check and test the Python services
	cd traffic-generator && ruff check src tests && mypy src && pytest -q
	cd bronze-writer && ruff check src tests && mypy src && pytest -q
	cd lakehouse && ruff check src tests && mypy src && pytest -q

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

cdc-up:          ## Phase 2a: start Kafka + Debezium + Kafka UI (http://localhost:8090)
	docker compose --profile cdc up -d

cdc-status:      ## Debezium connector status
	@curl -s http://localhost:8083/connectors/kaarangepay-postgres/status; echo

cdc-topics:      ## List Kafka topics
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list

cdc-down:        ## Stop CDC for a long time: delete connector, drop replication slot, stop services
	-curl -s -X DELETE http://localhost:8083/connectors/kaarangepay-postgres
	-docker compose exec postgres psql -U mmplatform -d mmplatform -c "SELECT pg_drop_replication_slot('kaarangepay_slot');"
	docker compose --profile cdc stop

bronze-up:       ## Phase 2b: start SeaweedFS + bronze-writer (needs the cdc profile)
	docker compose --profile cdc --profile bronze up -d --build

bronze-reconcile: ## Check the bronze layer: offsets contiguous, no duplicates
	docker compose --profile cdc --profile bronze run --rm bronze-writer reconcile

silver:          ## Phase 3a: rebuild silver (Delta) from bronze with Spark, then run the ledger checks
	docker compose --profile cdc --profile bronze --profile lake run --rm lake silver

fraud:           ## Phase 3b: streaming fraud detection on Kafka (processes what is there, then stops)
	docker compose --profile cdc --profile bronze --profile lake run --rm lake fraud

fraud-eval:      ## Phase 3b: precision / recall of the fraud alerts against the generator's labels
	docker compose --profile cdc --profile bronze --profile lake run --rm lake fraud-eval
