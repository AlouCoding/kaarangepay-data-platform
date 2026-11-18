"""Typing of silver tables, the ledger checks, and an end-to-end bronze -> silver run."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession

from bronze import Topic, account, entry, transaction
from kaarangepay_lake import quality
from kaarangepay_lake.cli import run_silver
from kaarangepay_lake.silver import TABLES, build

TREASURY, AWA, MOMAR = "00000000-0000-0000-0000-000000000001", "acc-awa", "acc-momar"


def healthy_ledger() -> tuple[Topic, Topic, Topic]:
    """Treasury issues 10,000 to Awa (topup), Awa sends 3,000 to Momar, a 50,000 transfer fails."""
    accounts = (Topic("accounts")
                .change("r", account(TREASURY, 0, "SYSTEM")).change("c", account(AWA, 0)).change("c", account(MOMAR, 0))
                .change("u", account(TREASURY, -10_000, "SYSTEM")).change("u", account(AWA, 10_000))
                .change("u", account(AWA, 7_000)).change("u", account(MOMAR, 3_000)))
    txs = (Topic("transactions").change("c", transaction("t1", TREASURY, AWA, 10_000))
           .change("c", transaction("t2", AWA, MOMAR, 3_000))
           .change("c", transaction("t3", MOMAR, AWA, 50_000, status="FAILED")))
    ledger = (Topic("ledger_entries")
              .change("c", entry(1, "t1", TREASURY, "DEBIT", 10_000)).change("c", entry(2, "t1", AWA, "CREDIT", 10_000))
              .change("c", entry(3, "t2", AWA, "DEBIT", 3_000)).change("c", entry(4, "t2", MOMAR, "CREDIT", 3_000)))
    return accounts, txs, ledger


def silver(spark: SparkSession, topics: tuple[Topic, Topic, Topic]) -> tuple[DataFrame, DataFrame, DataFrame]:
    a, t, e = (build(TABLES[x.table], x.df(spark)).data for x in topics)
    return a, t, e


def test_columns_are_typed(spark: SparkSession) -> None:
    _, txs, ledger = silver(spark, healthy_ledger())
    row = txs.where("id = 't1'").first()
    assert row is not None
    assert row["occurred_at"] == dt.datetime(2026, 11, 18, 10, 15, 30, 123456)  # UTC, microseconds kept
    assert row["occurred_date"] == dt.date(2026, 11, 18)
    assert sorted(r["signed_amount"] for r in ledger.where("transaction_id = 't2'").collect()) == [-3_000, 3_000]


def test_build_counts_events_and_current_rows(spark: SparkSession) -> None:
    accounts, _, _ = healthy_ledger()
    result = build(TABLES["accounts"], accounts.df(spark))
    assert (result.events, result.data.count(), result.rejected) == (7, 3, 0)


def test_healthy_ledger_passes_every_check(spark: SparkSession) -> None:
    checks = quality.run_all(*silver(spark, healthy_ledger()))
    assert [c.name for c in checks if not c.passed] == []


def test_a_lost_event_is_caught(spark: SparkSession) -> None:
    accounts, txs, ledger = healthy_ledger()
    del ledger.rows[3]  # Momar's credit never reached the lake
    failed = {c.name for c in quality.run_all(*silver(spark, (accounts, txs, ledger))) if not c.passed}
    assert failed == {"ledger: every transaction balanced", "ledger: balance = sum of entries"}


def test_a_stale_balance_is_caught(spark: SparkSession) -> None:
    accounts, txs, ledger = healthy_ledger()
    del accounts.rows[5]  # Awa's 7,000 update lost: silver keeps 10,000
    failed = {c.name for c in quality.run_all(*silver(spark, (accounts, txs, ledger))) if not c.passed}
    assert failed == {"ledger: sum of all balances = 0", "ledger: balance = sum of entries"}


def test_money_moved_by_a_failed_transaction_is_caught(spark: SparkSession) -> None:
    accounts, txs, ledger = healthy_ledger()
    ledger.change("c", entry(5, "t3", MOMAR, "DEBIT", 1)).change("c", entry(6, "t3", AWA, "CREDIT", 1))
    failed = {c.name for c in quality.run_all(*silver(spark, (accounts, txs, ledger))) if not c.passed}
    assert "ledger: failed transactions move no money" in failed


def test_end_to_end_run_is_idempotent(spark: SparkSession, tmp_path: Path) -> None:
    bronze, lake = tmp_path / "bronze", tmp_path / "silver"
    for topic in healthy_ledger():
        topic.df(spark).write.parquet(str(bronze / topic.table / "dt=2026-11-18" / "partition=0"))
    assert run_silver(spark, str(bronze), str(lake), "parquet")
    assert run_silver(spark, str(bronze), str(lake), "parquet")  # second run: same result, no duplicates
    assert spark.read.parquet(str(lake / "ledger_entries")).count() == 4
