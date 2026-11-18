# ADR 0008 — Silver layer: Spark rebuilds current-state Delta tables from bronze

- **Status:** Accepted
- **Date:** 2026-11-18

## Context
Bronze holds every CDC event as received (ADR 0007): a row can appear many times (create, then
updates), deletes are events, and the business columns are hidden inside a raw JSON payload.
Analytics, dbt (phase 4) and ML (phase 5) need **one clean, typed row per business entity**.

## Decisions
| Topic | Decision | Why |
|---|---|---|
| Engine | **Apache Spark 3.5.8** (PySpark), local mode in one container | Industry standard; same code runs on a cluster; 3.5 is the most deployed line |
| Table format | **Delta Lake 3.3.2** on S3 (SeaweedFS) | ACID overwrite, schema enforcement, time travel; no catalog service needed (Iceberg would need one) |
| Strategy | **Full rebuild** from bronze, then atomic overwrite | ~450k events = seconds; idempotent by construction; MERGE only when volume requires it |
| Current state | Latest event **per primary key, ordered by Kafka offset**; `d` removes the key | Debezium keys messages by PK, so all versions of a row are in one partition, in commit order |
| Bad payloads | Counted as `rejected`, never silently dropped | Bronze accepts everything; silver decides and reports |
| Dependencies | Delta + S3A jars baked into the image at build time | No download at run time: reproducible, works offline |

## Quality gate
After each rebuild the job re-checks, **on the lakehouse**, the three ledger invariants that
payment-core checks in PostgreSQL (ADR 0002), plus key uniqueness, required columns, referential
integrity and "failed transactions move no money". Exit code 1 if any check fails.

This turns the whole pipeline into one end-to-end test: if CDC, bronze or silver lost,
duplicated or reordered a single event, a balance or a transaction would no longer add up.

## Consequences
- ✅ Silver is disposable: delete it, rerun, get the same tables.
- ✅ Technical columns (`_cdc_op`, `_source_lsn`, `_kafka_partition`, `_kafka_offset`) keep lineage to bronze.
- ⚠️ While traffic is running, bronze lags PostgreSQL by up to 30 s: `accounts` updates may arrive
  before or after the matching ledger entries, so the drift check can fail transiently. Run it on a
  quiet system (traffic stopped, bronze caught up) to compare like with like.
- ⚠️ Silver is a snapshot of "now". History stays in bronze; slowly changing dimensions come in phase 4.
