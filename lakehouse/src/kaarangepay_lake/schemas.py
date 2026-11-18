"""Row schemas of the three source tables, as Debezium writes them in JSON.

With `schemas.enable=false` and Debezium's default `time.precision.mode`:
  * UUID and VARCHAR      -> JSON string
  * BIGINT / BIGSERIAL    -> JSON number
  * TIMESTAMPTZ           -> ISO-8601 string ("2026-11-18T10:15:30.123456Z")

Timestamps are therefore read as strings, then cast in `silver.py`. Keeping the JSON
schema separate from the silver schema makes the contract with Debezium explicit.
"""

from __future__ import annotations

from pyspark.sql.types import LongType, StringType, StructField, StructType


def _struct(*fields: tuple[str, object]) -> StructType:
    return StructType([StructField(name, dtype, True) for name, dtype in fields])  # type: ignore[arg-type]


S, L = StringType(), LongType()

ACCOUNTS_JSON = _struct(
    ("id", S), ("phone", S), ("owner_name", S), ("account_type", S), ("status", S),
    ("currency", S), ("balance", L), ("version", L), ("created_at", S), ("updated_at", S),
)

TRANSACTIONS_JSON = _struct(
    ("id", S), ("idempotency_key", S), ("request_hash", S), ("transaction_type", S), ("status", S),
    ("source_account_id", S), ("destination_account_id", S), ("amount", L), ("fee", L),
    ("currency", S), ("failure_reason", S), ("occurred_at", S), ("recorded_at", S),
)

LEDGER_ENTRIES_JSON = _struct(
    ("id", L), ("transaction_id", S), ("account_id", S), ("direction", S), ("amount", L),
    ("balance_after", L), ("occurred_at", S), ("recorded_at", S),
)
