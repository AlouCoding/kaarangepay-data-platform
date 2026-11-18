"""The consume -> batch -> write -> commit loop."""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Protocol

from bronze_writer.batching import Batcher, PartitionBatch
from bronze_writer.records import RawMessage, to_row
from bronze_writer.storage import ObjectStore, to_parquet

log = logging.getLogger("bronze_writer")


class ConsumerPort(Protocol):
    def poll(self, timeout_s: float) -> RawMessage | None: ...

    def commit(self, topic: str, partition: int, next_offset: int) -> None: ...


class BronzeWriter:
    def __init__(
        self,
        consumer: ConsumerPort,
        store: ObjectStore,
        batcher: Batcher,
        clock: Callable[[], float] = time.monotonic,
        wall_clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self.consumer = consumer
        self.store = store
        self.batcher = batcher
        self.clock = clock
        self.wall_clock_ms = wall_clock_ms
        self.rows_written: Counter[str] = Counter()
        self.files_written = 0

    def step(self, poll_timeout_s: float = 1.0) -> None:
        """One iteration: read at most one message, then flush what is full or too old."""
        message = self.consumer.poll(poll_timeout_s)
        if message is not None:
            full = self.batcher.add(message, to_row(message, self.wall_clock_ms()), self.clock())
            if full is not None:
                self.flush(full)
        for batch in self.batcher.expired(self.clock()):
            self.flush(batch)

    def flush(self, batch: PartitionBatch) -> None:
        """Write first, commit second: a crash in between only causes an idempotent rewrite."""
        if not len(batch):
            return
        key = batch.object_key()
        self.store.put(key, to_parquet(batch.rows))
        self.consumer.commit(batch.topic, batch.partition, batch.last_offset + 1)
        self.rows_written[batch.topic] += len(batch)
        self.files_written += 1
        log.info("wrote %s (%d rows, offsets %d-%d)", key, len(batch),
                 batch.first_message.offset if batch.first_message else -1, batch.last_offset)

    def shutdown(self) -> None:
        for batch in self.batcher.drain():
            self.flush(batch)
