# ADR 0002 — Double-entry ledger with a treasury account

- **Status:** Accepted
- **Date:** 2026-11-17

## Context
Storing only a `balance` column makes errors invisible: if a bug credits 500 XOF
without debiting anyone, nothing detects it. Downstream analytics would silently
report wrong numbers.

## Decision
- Every transaction writes **ledger entries** whose total debits equal total
  credits. Direction is expressed from the wallet's perspective
  (`DEBIT` = money leaves, `CREDIT` = money enters).
- E-money enters the system only through a `FLOAT_TOPUP` from the **TREASURY**
  system account to an agent. TREASURY is allowed to go negative: its balance is
  the mirror of all e-money in circulation.
- Therefore **the sum of all account balances is always exactly 0.**
- `accounts.balance` is kept as a denormalised cache for fast reads, protected
  by a `CHECK (balance >= 0)` for non-system accounts.
- Each entry stores `balance_after`, so any statement can be audited line by line.

## Consequences
- ✅ Three invariants can be checked automatically at any time
  (`GET /api/v1/ledger/integrity`), and later in dbt tests:
  1. sum of balances = 0;
  2. each transaction's debits = credits;
  3. each account balance = its credits − its debits.
- ✅ Gives the data layer a real reconciliation use case.
- ❌ The FEES and TREASURY rows are locked by many transactions (hot rows),
  which caps throughput. Known trade-off; mitigation later: accumulate fees
  asynchronously or shard the fee account.
