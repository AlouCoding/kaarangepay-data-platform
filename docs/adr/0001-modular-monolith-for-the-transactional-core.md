# ADR 0001 — A modular monolith for the transactional core

- **Status:** Accepted
- **Date:** 2026-11-17

## Context
The project is a **data platform**: its value lies in ingestion (CDC), streaming,
the lakehouse, modelling and data quality. The transactional services exist to
produce realistic, *correct* data.

A transfer touches the source account, the destination account and the fee
account. Splitting accounts, ledger and transfers into separate services would
force a distributed transaction (Saga + compensations) for every payment — a
large amount of complexity that serves the backend story, not the data story.

## Decision
`payment-core` is a single Spring Boot service with clear internal modules
(`account`, `ledger`, `transaction`). Every money movement is one ACID
PostgreSQL transaction.

## Consequences
- ✅ Strong consistency for free: a transfer can never be half-applied.
- ✅ One database to capture with Debezium in phase 2.
- ✅ Module boundaries (packages) keep a future split possible.
- ❌ No independent scaling per module. Acceptable at this scale.
- If the project later needs to showcase Sagas, `transfer` is the module to
  extract first.
