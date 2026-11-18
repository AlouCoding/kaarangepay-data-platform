"""Data quality checks on silver.

The three ledger invariants are **the same ones payment-core checks in SQL**
(`/api/v1/ledger/integrity`, ADR 0002). Re-checking them on the lakehouse is a real
end-to-end reconciliation: if CDC, bronze or silver had lost, duplicated or reordered a single
event, at least one of them would fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    observed: int   # the measured value (0 is the expected value for every check here)
    detail: str


def _count(df: DataFrame) -> int:
    return int(df.count())


def unique_key(df: DataFrame, table: str, keys: list[str]) -> CheckResult:
    dupes = _count(df.groupBy(*keys).count().where(F.col("count") > 1))
    return CheckResult(f"{table}: primary key unique", dupes == 0, dupes, "keys appearing more than once")


def not_null(df: DataFrame, table: str, columns: list[str]) -> CheckResult:
    cond = F.lit(False)
    for c in columns:
        cond = cond | F.col(c).isNull()
    bad = _count(df.where(cond))
    return CheckResult(f"{table}: required columns not null", bad == 0, bad, ", ".join(columns))


def sum_of_balances(accounts: DataFrame) -> CheckResult:
    total = accounts.agg(F.coalesce(F.sum("balance"), F.lit(0)).alias("s")).first()
    value = int(total["s"]) if total is not None else 0
    return CheckResult("ledger: sum of all balances = 0", value == 0, value, "TREASURY mirrors issued e-money")


def unbalanced_transactions(ledger: DataFrame) -> CheckResult:
    bad = _count(ledger.groupBy("transaction_id").agg(F.sum("signed_amount").alias("net"))
                 .where(F.col("net") != 0))
    return CheckResult("ledger: every transaction balanced", bad == 0, bad, "debits = credits per transaction")


def accounts_with_drift(accounts: DataFrame, ledger: DataFrame) -> CheckResult:
    net = ledger.groupBy("account_id").agg(F.sum("signed_amount").alias("net"))
    bad = _count(
        accounts.join(net, accounts["id"] == net["account_id"], "left")
        .where(accounts["balance"] != F.coalesce(net["net"], F.lit(0)))
    )
    return CheckResult("ledger: balance = sum of entries", bad == 0, bad, "per account")


def orphan_entries(ledger: DataFrame, transactions: DataFrame, accounts: DataFrame) -> CheckResult:
    no_tx = ledger.join(transactions, ledger["transaction_id"] == transactions["id"], "left_anti")
    no_acc = ledger.join(accounts, ledger["account_id"] == accounts["id"], "left_anti")
    bad = _count(no_tx) + _count(no_acc)
    return CheckResult("ledger: entries reference known rows", bad == 0, bad, "transaction and account exist")


def failed_without_entries(transactions: DataFrame, ledger: DataFrame) -> CheckResult:
    failed = transactions.where(F.col("status") == "FAILED").select("id")
    bad = _count(failed.join(ledger, failed["id"] == ledger["transaction_id"], "left_semi"))
    return CheckResult("ledger: failed transactions move no money", bad == 0, bad, "no entry for FAILED")


def run_all(accounts: DataFrame, transactions: DataFrame, ledger: DataFrame) -> list[CheckResult]:
    return [
        unique_key(accounts, "accounts", ["id"]),
        unique_key(transactions, "transactions", ["id"]),
        unique_key(ledger, "ledger_entries", ["id"]),
        not_null(transactions, "transactions", ["id", "status", "amount", "occurred_at"]),
        not_null(ledger, "ledger_entries", ["id", "transaction_id", "account_id", "amount", "occurred_at"]),
        sum_of_balances(accounts),
        unbalanced_transactions(ledger),
        accounts_with_drift(accounts, ledger),
        orphan_entries(ledger, transactions, accounts),
        failed_without_entries(transactions, ledger),
    ]
