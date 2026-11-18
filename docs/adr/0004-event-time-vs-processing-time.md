# ADR 0004 — Separate event time from processing time

- **Status:** Accepted
- **Date:** 2026-11-17

## Context
The streaming layer (phase 3) aggregates by time window. To show realistic
patterns (end-of-month paydays, Tabaski, day/night cycle) without running the
generator for months, the generator must be able to **simulate time**.

## Decision
- Each transaction and ledger entry has two timestamps:
  - `occurred_at` — **event time**, when the payment happened for the customer;
  - `recorded_at` — **processing time**, set by the server clock when the row is written.
- By default `occurred_at` comes from the server clock.
- When `platform.simulation.allow-client-clock=true` (dev / demo only), the
  server accepts an `X-Simulated-Time` header (ISO-8601) and uses it as
  `occurred_at`. **This flag is off by default and must never be enabled in
  production.**

## Consequences
- ✅ Months of realistic history can be generated in minutes (backfill).
- ✅ The data has genuine event-time/processing-time skew, which is exactly
  what watermarks and late-data handling are designed for in phase 3.
- ❌ A simulation-only code path exists in the service; it is isolated in
  `TransactionClock` and covered by tests.
