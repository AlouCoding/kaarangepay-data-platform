"""Builds bronze rows exactly like bronze-writer stores them (raw Debezium envelope in `payload`)."""

from __future__ import annotations

import json
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType

BRONZE = StructType([
    StructField("kafka_topic", StringType(), False),
    StructField("kafka_partition", IntegerType(), False),
    StructField("kafka_offset", LongType(), False),
    StructField("kafka_timestamp_ms", LongType(), True),
    StructField("kafka_key", StringType(), True),
    StructField("op", StringType(), True),
    StructField("source_table", StringType(), True),
    StructField("source_lsn", LongType(), True),
    StructField("source_tx_id", LongType(), True),
    StructField("debezium_ts_ms", LongType(), True),
    StructField("payload", StringType(), True),
    StructField("ingested_at_ms", LongType(), False),
])


class Topic:
    """Appends events to one partition of a fake topic, with increasing offsets."""

    def __init__(self, table: str, partition: int = 0) -> None:
        self.table, self.partition, self.offset = table, partition, 0
        self.rows: list[dict[str, Any]] = []

    def _add(self, op: str | None, payload: str | None) -> Topic:
        self.rows.append({
            "kafka_topic": f"kaarangepay.public.{self.table}", "kafka_partition": self.partition,
            "kafka_offset": self.offset, "kafka_timestamp_ms": 0, "kafka_key": None, "op": op,
            "source_table": self.table, "source_lsn": 1000 + self.offset, "source_tx_id": 1,
            "debezium_ts_ms": 0, "payload": payload, "ingested_at_ms": 0,
        })
        self.offset += 1
        return self

    def change(self, op: str, after: dict[str, Any] | None = None, before: dict[str, Any] | None = None) -> Topic:
        envelope = {"before": before, "after": after, "op": op, "ts_ms": 0, "source": {"table": self.table}}
        return self._add(op, json.dumps(envelope))

    def tombstone(self) -> Topic:
        return self._add(None, None)

    def raw(self, payload: str) -> Topic:
        return self._add(None, payload)

    def df(self, spark: SparkSession) -> DataFrame:
        return spark.createDataFrame(self.rows, BRONZE)


TS = "2026-11-18T10:15:30.123456Z"


def account(id_: str, balance: int, type_: str = "CUSTOMER") -> dict[str, Any]:
    return {"id": id_, "phone": f"+22177{id_[-7:]}", "owner_name": "Awa", "account_type": type_,
            "status": "ACTIVE", "currency": "XOF", "balance": balance, "version": 0,
            "created_at": TS, "updated_at": TS}


def transaction(id_: str, src: str, dst: str, amount: int, status: str = "COMPLETED", fee: int = 0) -> dict[str, Any]:
    return {"id": id_, "idempotency_key": f"k-{id_}", "request_hash": "h", "transaction_type": "TRANSFER",
            "status": status, "source_account_id": src, "destination_account_id": dst, "amount": amount,
            "fee": fee, "currency": "XOF", "failure_reason": None if status == "COMPLETED" else "INSUFFICIENT_FUNDS",
            "occurred_at": TS, "recorded_at": TS}


def entry(id_: int, tx: str, acc: str, direction: str, amount: int, balance_after: int = 0) -> dict[str, Any]:
    return {"id": id_, "transaction_id": tx, "account_id": acc, "direction": direction, "amount": amount,
            "balance_after": balance_after, "occurred_at": TS, "recorded_at": TS}
