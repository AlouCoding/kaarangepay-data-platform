"""In-memory stand-ins for Kafka and S3, faithful to what the writer relies on."""

from __future__ import annotations

import json
from collections.abc import Iterator

from bronze_writer.records import RawMessage


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.events: list[str] = []
        self.fail_next_put = False

    def ensure_bucket(self) -> None:
        pass

    def put(self, key: str, data: bytes) -> None:
        if self.fail_next_put:
            self.fail_next_put = False
            raise OSError("storage unavailable")
        self.objects[key] = data
        self.events.append(f"put {key}")

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        return iter(sorted(k for k in self.objects if k.startswith(prefix)))


class FakeConsumer:
    """A topic log plus committed offsets; restarts resume from the committed offset."""

    def __init__(self, log: list[RawMessage], events: list[str]) -> None:
        self.log = log
        self.events = events
        self.committed: dict[tuple[str, int], int] = {}
        self._cursor = 0

    def poll(self, timeout_s: float) -> RawMessage | None:
        while self._cursor < len(self.log):
            message = self.log[self._cursor]
            self._cursor += 1
            if message.offset >= self.committed.get((message.topic, message.partition), 0):
                return message
        return None

    def commit(self, topic: str, partition: int, next_offset: int) -> None:
        self.committed[(topic, partition)] = next_offset
        self.events.append(f"commit {topic}/{partition}@{next_offset}")

    def restart(self) -> None:
        """Simulates a crash + restart: in-memory position lost, committed offsets kept."""
        self._cursor = 0


TOPIC = "kaarangepay.public.transactions"


def message(offset: int, partition: int = 0, topic: str = TOPIC, ts_ms: int = 1_795_020_000_000,
            value: bytes | None = None) -> RawMessage:
    if value is None:
        value = json.dumps({
            "before": None,
            "after": {"id": f"tx-{partition}-{offset}", "amount": 1000},
            "source": {"table": "transactions", "lsn": 1000 + offset, "txId": 500 + offset},
            "op": "c",
            "ts_ms": ts_ms,
        }).encode()
    return RawMessage(topic, partition, offset, ts_ms, f'{{"id":"tx-{offset}"}}'.encode(), value)
