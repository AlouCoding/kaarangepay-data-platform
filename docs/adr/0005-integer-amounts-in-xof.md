# ADR 0005 — Integer amounts in XOF

- **Status:** Accepted
- **Date:** 2026-11-17

## Context
Floating-point types cannot represent money exactly (0.1 + 0.2 ≠ 0.3).
The West African CFA franc (XOF) has no subunit in practice.

## Decision
- All amounts are `BIGINT` / `long` in XOF units. No `float`, no `double`.
- Fees are computed in basis points with integer arithmetic and rounded
  **down** (in the customer's favour), then capped.

## Consequences
- ✅ Exact arithmetic, trivial reconciliation.
- ❌ Multi-currency would require a currency-aware money type. Out of scope.
