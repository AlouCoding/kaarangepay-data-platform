# ADR 0006 — Change Data Capture with Debezium and Kafka

- **Status:** Accepted
- **Date:** 2026-11-18

## Context
The data platform needs every change made in `payment-core` (new accounts, transactions,
ledger entries, balance updates) as a stream, in order, without losing any.

Options considered:

| Option | Problem |
|---|---|
| Poll the database (`SELECT … WHERE recorded_at > ?`) | Misses updates between polls, misses deletes, loads the OLTP database |
| Dual write: the service writes to PostgreSQL **and** publishes to Kafka | Two systems, no shared transaction: a crash between the two writes loses or duplicates events |
| Transactional outbox table + relay | Correct, but requires changing the service and adds a table |
| **Log-based CDC (Debezium)** | Reads PostgreSQL's write-ahead log: every committed change, in commit order, with no change to the service |

## Decision
- PostgreSQL runs with `wal_level=logical` (already set in phase 1).
- **Debezium's PostgreSQL connector** (Kafka Connect) reads the WAL through the `pgoutput`
  plugin, using a replication slot `kaarangepay_slot` and a publication limited to
  `accounts`, `transactions`, `ledger_entries`.
- One Kafka topic per table: `kaarangepay.public.<table>`, 3 partitions, keyed by primary key
  → all changes of one row are ordered within one partition.
- `snapshot.mode=initial`: on first start, Debezium publishes the current content of the tables
  (`op = "r"`), then streams new changes (`op = "c"`, `"u"`, `"d"`).
- Messages keep the **full Debezium envelope** (`before`, `after`, `op`, `source`, `ts_ms`).
  This is the raw, replayable record that the bronze layer will store as-is.
- Kafka runs as a **single KRaft node** (no ZooKeeper), replication factor 1.
- Phase 2a uses JSON without embedded schemas for readability. Avro + Schema Registry come in 2b.

## Consequences
- ✅ No code change in `payment-core`; capture is exactly the committed state.
- ✅ Insert-only tables (`transactions`, `ledger_entries`) give a simple reconciliation:
  **messages in the topic = rows in the table**.
- ⚠️ A replication slot **retains WAL until Debezium confirms it**. If the connector stays
  stopped, PostgreSQL's disk grows. Monitor the slot lag; drop the slot when CDC is removed.
- ⚠️ Single broker, replication factor 1: no fault tolerance. Acceptable on a laptop only.
- ⚠️ The connector uses the database owner account. In production: a dedicated role with
  `REPLICATION` and `SELECT` only, and the password in a secret store.
