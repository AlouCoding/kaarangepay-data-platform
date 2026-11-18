"""Silver layer: one clean, typed table per source table, holding its **current state**.

    bronze/<table>/...parquet  --parse_changes-->  changes  --current_state-->  typed  -->  silver/<table>

Silver is rebuilt from bronze on every run (full recompute, then atomic overwrite of the Delta
table). With ~450k events this takes seconds, and it makes the job idempotent: running it twice
gives the same result. Incremental MERGE will only be worth it when bronze gets much larger.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from kaarangepay_lake.cdc import CDC_COLUMNS, current_state, parse_changes
from kaarangepay_lake.schemas import ACCOUNTS_JSON, LEDGER_ENTRIES_JSON, TRANSACTIONS_JSON


def _ts(name: str) -> Column:
    """ISO-8601 string from Debezium -> TIMESTAMP (session time zone is UTC)."""
    return F.to_timestamp(F.col(name)).alias(name)


def _typed_accounts(df: DataFrame) -> DataFrame:
    return df.select(
        "id", "phone", "owner_name", "account_type", "status", "currency", "balance", "version",
        _ts("created_at"), _ts("updated_at"), *CDC_COLUMNS,
    )


def _typed_transactions(df: DataFrame) -> DataFrame:
    return df.select(
        "id", "idempotency_key", "transaction_type", "status", "source_account_id",
        "destination_account_id", "amount", "fee", "currency", "failure_reason",
        _ts("occurred_at"), _ts("recorded_at"), *CDC_COLUMNS,
    ).withColumn("occurred_date", F.to_date("occurred_at"))  # partition column (event time)


def _typed_ledger_entries(df: DataFrame) -> DataFrame:
    signed = F.when(F.col("direction") == "CREDIT", F.col("amount")).otherwise(-F.col("amount"))
    return df.select(
        "id", "transaction_id", "account_id", "direction", "amount", "balance_after",
        _ts("occurred_at"), _ts("recorded_at"), *CDC_COLUMNS,
    ).withColumn("signed_amount", signed).withColumn("occurred_date", F.to_date("occurred_at"))


@dataclass(frozen=True)
class SilverTable:
    name: str
    json_schema: StructType
    keys: list[str]
    typed: Callable[[DataFrame], DataFrame]
    partition_by: list[str]


TABLES: dict[str, SilverTable] = {
    t.name: t
    for t in [
        SilverTable("accounts", ACCOUNTS_JSON, ["id"], _typed_accounts, []),
        SilverTable("transactions", TRANSACTIONS_JSON, ["id"], _typed_transactions, ["occurred_date"]),
        SilverTable("ledger_entries", LEDGER_ENTRIES_JSON, ["id"], _typed_ledger_entries, ["occurred_date"]),
    ]
}


@dataclass(frozen=True)
class SilverResult:
    table: SilverTable
    data: DataFrame       # current state, typed
    events: int           # change events read from bronze (tombstones excluded)
    rejected: int         # events silver could not interpret


def build(table: SilverTable, bronze: DataFrame) -> SilverResult:
    parsed = parse_changes(bronze, table.json_schema)
    data = table.typed(current_state(parsed.changes, table.keys))
    return SilverResult(table, data, parsed.changes.count(), parsed.rejected.count())
