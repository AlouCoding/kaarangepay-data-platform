"""Per-partition batches and deterministic object keys.

Exactly-once **effect** in storage, with at-least-once Kafka delivery:

1. a batch always covers consecutive offsets of ONE partition;
2. its object key depends only on the batch's **first offset**;
3. the Kafka offset is committed only **after** the object is written.

If the writer crashes after the upload but before the commit, it restarts from the
same first offset, rebuilds a batch starting there and **overwrites the same object**.
Nothing is lost (commit after write) and nothing is duplicated (same key).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bronze_writer.records import RawMessage, table_name


@dataclass
class PartitionBatch:
    topic: str
    partition: int
    opened_at: float
    rows: list[dict[str, Any]] = field(default_factory=list)
    first_message: RawMessage | None = None
    last_offset: int = -1

    def add(self, message: RawMessage, row: dict[str, Any]) -> None:
        if self.first_message is None:
            self.first_message = message
        elif message.offset <= self.last_offset:
            raise ValueError(
                f"Offsets must increase within a partition: {message.offset} after {self.last_offset}")
        self.rows.append(row)
        self.last_offset = message.offset

    def __len__(self) -> int:
        return len(self.rows)

    def object_key(self) -> str:
        """bronze key, e.g. transactions/dt=2026-11-18/partition=2/offset=000000044794.parquet"""
        assert self.first_message is not None, "empty batch has no key"
        ts_ms = self.first_message.timestamp_ms or 0
        day = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat()
        return (f"{table_name(self.topic)}/dt={day}/partition={self.partition}/"
                f"offset={self.first_message.offset:012d}.parquet")


class Batcher:
    """Groups rows by (topic, partition) and says when a batch must be flushed."""

    def __init__(self, max_records: int, max_seconds: float) -> None:
        if max_records < 1 or max_seconds <= 0:
            raise ValueError("max_records >= 1 and max_seconds > 0 are required")
        self.max_records = max_records
        self.max_seconds = max_seconds
        self._batches: dict[tuple[str, int], PartitionBatch] = {}

    def add(self, message: RawMessage, row: dict[str, Any], now: float) -> PartitionBatch | None:
        """Adds a row; returns the batch if it just became full."""
        key = (message.topic, message.partition)
        batch = self._batches.get(key)
        if batch is None:
            batch = self._batches[key] = PartitionBatch(message.topic, message.partition, opened_at=now)
        batch.add(message, row)
        if len(batch) >= self.max_records:
            return self._batches.pop(key)
        return None

    def expired(self, now: float) -> list[PartitionBatch]:
        """Removes and returns batches older than max_seconds (low traffic must still land)."""
        keys = [k for k, b in self._batches.items() if now - b.opened_at >= self.max_seconds]
        return [self._batches.pop(k) for k in keys]

    def drain(self) -> list[PartitionBatch]:
        """Removes and returns every pending batch (shutdown)."""
        batches = list(self._batches.values())
        self._batches.clear()
        return batches

    def discard(self, topic: str, partition: int) -> None:
        """Partition revoked: its uncommitted rows will be re-read by the next owner."""
        self._batches.pop((topic, partition), None)
