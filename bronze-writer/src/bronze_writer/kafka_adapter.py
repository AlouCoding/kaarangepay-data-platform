"""confluent-kafka adapter for the ConsumerPort (the only module that imports the client)."""

from __future__ import annotations

import logging
from typing import Any

from bronze_writer.batching import Batcher
from bronze_writer.records import RawMessage

log = logging.getLogger("bronze_writer")


class KafkaConsumer:
    def __init__(self, bootstrap: str, group_id: str, topics: list[str], batcher: Batcher) -> None:
        from confluent_kafka import Consumer

        self._consumer = Consumer({
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "enable.auto.commit": False,        # we commit only after the file is written
            "auto.offset.reset": "earliest",    # first run: start from the beginning of each topic
            "isolation.level": "read_committed",
        })
        self._batcher = batcher

        def on_revoke(_consumer: Any, partitions: list[Any]) -> None:
            for tp in partitions:
                self._batcher.discard(tp.topic, tp.partition)
            log.info("partitions revoked: %s", [(tp.topic, tp.partition) for tp in partitions])

        self._consumer.subscribe(topics, on_revoke=on_revoke)

    def poll(self, timeout_s: float) -> RawMessage | None:
        msg = self._consumer.poll(timeout_s)
        if msg is None:
            return None
        if msg.error():
            log.warning("kafka error: %s", msg.error())
            return None
        topic, partition, offset = msg.topic(), msg.partition(), msg.offset()
        if topic is None or partition is None or offset is None:
            return None
        ts_type, ts = msg.timestamp()
        return RawMessage(
            topic=topic,
            partition=partition,
            offset=offset,
            timestamp_ms=ts if ts_type != 0 else None,
            key=msg.key(),
            value=msg.value(),
        )

    def commit(self, topic: str, partition: int, next_offset: int) -> None:
        from confluent_kafka import TopicPartition

        self._consumer.commit(offsets=[TopicPartition(topic, partition, next_offset)], asynchronous=False)

    def close(self) -> None:
        self._consumer.close()
