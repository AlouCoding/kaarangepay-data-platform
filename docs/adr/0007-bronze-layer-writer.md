# ADR 0007 — Bronze layer: our own Kafka consumer writing Parquet to S3-compatible storage

- **Status:** Accepted
- **Date:** 2026-11-18

## Context
The bronze layer stores **every CDC event exactly as received**, so that any later layer
(silver, gold, ML features) can be rebuilt from scratch. It must lose nothing and duplicate nothing.

Two choices were needed: the storage, and the component that moves data from Kafka to it.

## Decision 1 — Storage: SeaweedFS (S3-compatible)
- MinIO, the usual local S3, stopped publishing free Docker images in October 2025 and entered
  maintenance mode. Building it from source is not reasonable on a slow connection.
- **SeaweedFS** is open source (Apache 2.0), maintained, exposes an S3 API, and ships as one image.
- The writer only talks **S3** (boto3): switching to AWS S3 or another S3-compatible store is a
  configuration change, not a code change.

## Decision 2 — Writer: a small Python consumer instead of a Kafka Connect S3 sink
| Option | Why not / why |
|---|---|
| Kafka Connect S3 sink connector | Extra plugin download and configuration; behaviour hidden in a black box |
| **Own consumer (`bronze-writer`)** | ~300 lines, fully unit-tested, explicit delivery guarantees, and it shows how Kafka consumption really works |

## Delivery guarantee: exactly-once **effect** with at-least-once delivery
1. Auto-commit is **off**. Rows are buffered **per partition**.
2. A batch is flushed when it reaches `BATCH_MAX_RECORDS` (5,000) or `BATCH_MAX_SECONDS` (30 s).
3. The Parquet file is written **first**; the Kafka offset is committed **second**.
4. The object key depends only on the batch's **first offset**:
   `transactions/dt=2026-11-18/partition=2/offset=000000044794.parquet`

If the process dies after the write but before the commit, it restarts from the same offset,
rebuilds a batch starting there and **overwrites the same object**. Nothing is lost (commit after
write), nothing is duplicated (deterministic key). This scenario is an automated test.

## File layout
- Format: **Parquet** (columnar, compressed with zstd) — read directly by Spark, DuckDB, pandas.
- Partitioning: `table / dt=<day of the first event> / partition=<kafka partition>`.
- Content: Kafka coordinates (topic, partition, offset, timestamp, key), a few Debezium envelope
  fields (`op`, table, LSN, transaction id, `ts_ms`) and the **raw payload untouched**.

## Consequences
- ✅ Reconciliation tool: per partition, offsets must be contiguous with **no gap and no duplicate**;
  insert-only tables can then be compared with PostgreSQL row counts.
- ✅ Bronze accepts everything (tombstones, malformed JSON): interpretation belongs to silver.
- ⚠️ A batch never mixes partitions; with low traffic this yields many small files. Compaction
  will be handled when building silver.
- ⚠️ Avro + Schema Registry are postponed: bronze keeps the raw JSON, which is enough until schema
  evolution becomes a real need.
- ⚠️ SeaweedFS runs without authentication on the local network. In production: access keys,
  TLS and bucket policies.
