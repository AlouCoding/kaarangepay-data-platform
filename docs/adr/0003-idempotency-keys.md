# ADR 0003 — Mandatory idempotency keys on money movements

- **Status:** Accepted
- **Date:** 2026-11-17

## Context
Mobile networks drop connections. A client that does not receive the response to
a transfer will retry. Without protection, the customer is debited twice.

## Decision
- `POST /api/v1/transactions` requires an `Idempotency-Key` header (max 64 chars).
- The key is stored in `transactions.idempotency_key` (UNIQUE), together with a
  SHA-256 hash of the request payload.
- Same key + same payload → the stored result is returned (with header
  `Idempotent-Replay: true`), even if the original attempt FAILED.
- Same key + different payload → `409 Conflict`.
- Two concurrent requests with the same key: the second one waits on the row
  locks, then hits the UNIQUE constraint; the service catches it and replays the
  first result.

## Consequences
- ✅ Exactly-once effect for clients that retry correctly.
- ✅ Failed attempts are recorded too (`status = FAILED`): useful data for
  analytics and fraud detection.
- ❌ Keys are kept forever. A retention policy can be added later.
