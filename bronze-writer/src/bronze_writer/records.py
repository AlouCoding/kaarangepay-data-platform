"""One Kafka message -> one bronze row.

Bronze keeps the **raw** Debezium payload (as a JSON string) so nothing is lost and
history can always be replayed. A few envelope fields are extracted next to it to make
the files easy to filter and to reconcile; nothing is interpreted beyond that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

_FIELDS: list[pa.Field[Any]] = [
    pa.field("kafka_topic", pa.string(), nullable=False),
    pa.field("kafka_partition", pa.int32(), nullable=False),
    pa.field("kafka_offset", pa.int64(), nullable=False),
    pa.field("kafka_timestamp_ms", pa.int64()),
    pa.field("kafka_key", pa.string()),
    pa.field("op", pa.string()),            # r = snapshot, c = create, u = update, d = delete
    pa.field("source_table", pa.string()),
    pa.field("source_lsn", pa.int64()),
    pa.field("source_tx_id", pa.int64()),
    pa.field("debezium_ts_ms", pa.int64()),
    pa.field("payload", pa.string()),       # the full raw Debezium envelope, untouched
    pa.field("ingested_at_ms", pa.int64(), nullable=False),
]
BRONZE_SCHEMA = pa.schema(_FIELDS)


@dataclass(frozen=True)
class RawMessage:
    """What the writer needs from a Kafka message (decoupled from the Kafka client)."""

    topic: str
    partition: int
    offset: int
    timestamp_ms: int | None
    key: bytes | None
    value: bytes | None


def _decode(data: bytes | None) -> str | None:
    return None if data is None else data.decode("utf-8", errors="replace")


def to_row(message: RawMessage, ingested_at_ms: int) -> dict[str, Any]:
    """Builds a bronze row. Never raises on bad payloads: bronze must accept everything."""
    payload = _decode(message.value)
    envelope: dict[str, Any] = {}
    if payload:
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                envelope = parsed
        except json.JSONDecodeError:
            pass  # kept as-is in `payload`; downstream layers decide what to do with it
    source = envelope.get("source") if isinstance(envelope.get("source"), dict) else {}
    assert isinstance(source, dict)
    return {
        "kafka_topic": message.topic,
        "kafka_partition": message.partition,
        "kafka_offset": message.offset,
        "kafka_timestamp_ms": message.timestamp_ms,
        "kafka_key": _decode(message.key),
        "op": envelope.get("op"),
        "source_table": source.get("table"),
        "source_lsn": source.get("lsn"),
        "source_tx_id": source.get("txId"),
        "debezium_ts_ms": envelope.get("ts_ms"),
        "payload": payload,   # None for a tombstone (delete marker)
        "ingested_at_ms": ingested_at_ms,
    }


def table_name(topic: str) -> str:
    """kaarangepay.public.transactions -> transactions"""
    return topic.rsplit(".", 1)[-1]
