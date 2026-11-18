import io

import pyarrow.parquet as pq
import pytest
from fakes import TOPIC, FakeConsumer, FakeStore, message

from bronze_writer.batching import Batcher
from bronze_writer.reconcile import reconcile
from bronze_writer.records import RawMessage, table_name, to_row
from bronze_writer.writer import BronzeWriter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make(log: list[RawMessage], max_records: int = 3, max_seconds: float = 30.0):  # type: ignore[no-untyped-def]
    store = FakeStore()
    consumer = FakeConsumer(log, store.events)
    clock = Clock()
    writer = BronzeWriter(consumer, store, Batcher(max_records, max_seconds), clock=clock,
                          wall_clock_ms=lambda: 42)
    return writer, consumer, store, clock


def drain(writer: BronzeWriter, steps: int = 50) -> None:
    for _ in range(steps):
        writer.step(0)


def test_row_keeps_raw_payload_and_extracts_envelope() -> None:
    row = to_row(message(7), ingested_at_ms=42)
    assert row["op"] == "c"
    assert row["source_table"] == "transactions"
    assert row["source_lsn"] == 1007
    assert row["source_tx_id"] == 507
    assert '"amount": 1000' in row["payload"]
    assert table_name(TOPIC) == "transactions"


def test_bronze_accepts_tombstones_and_garbage() -> None:
    tombstone = to_row(message(1, value=b""), 0) | to_row(RawMessage(TOPIC, 0, 2, None, None, None), 0)
    assert tombstone["payload"] is None and tombstone["op"] is None
    garbage = to_row(message(3, value=b"not json"), 0)
    assert garbage["payload"] == "not json" and garbage["op"] is None


def test_full_batch_is_written_then_committed() -> None:
    writer, _, store, _ = make([message(o) for o in range(3)])
    drain(writer)
    key = "transactions/dt=2026-11-18/partition=0/offset=000000000000.parquet"
    assert store.events == [f"put {key}", f"commit {TOPIC}/0@3"]   # write BEFORE commit
    table = pq.read_table(io.BytesIO(store.objects[key]))
    assert table.num_rows == 3
    assert table.column("kafka_offset").to_pylist() == [0, 1, 2]


def test_slow_traffic_is_flushed_after_max_seconds() -> None:
    writer, consumer, store, clock = make([message(0)], max_records=1000, max_seconds=30)
    drain(writer, 2)
    assert store.objects == {}
    clock.now = 31
    writer.step(0)
    assert len(store.objects) == 1
    assert consumer.committed[(TOPIC, 0)] == 1


def test_partitions_are_batched_separately() -> None:
    log = [message(0, partition=0), message(0, partition=1), message(1, partition=0), message(1, partition=1)]
    writer, consumer, store, _ = make(log, max_records=2)
    drain(writer)
    assert sorted(store.objects) == [
        "transactions/dt=2026-11-18/partition=0/offset=000000000000.parquet",
        "transactions/dt=2026-11-18/partition=1/offset=000000000000.parquet",
    ]
    assert consumer.committed == {(TOPIC, 0): 2, (TOPIC, 1): 2}


def test_crash_between_write_and_commit_rewrites_the_same_object() -> None:
    """The exactly-once-effect argument of ADR 0007, executed."""
    writer, consumer, store, _ = make([message(o) for o in range(6)], max_records=3)
    # 1st run: batch 0-2 written but the process dies before committing it.
    original_commit = consumer.commit
    consumer.commit = lambda *a: (_ for _ in ()).throw(RuntimeError("killed"))  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        drain(writer)
    assert len(store.objects) == 1 and consumer.committed == {}

    # Restart: same group, nothing committed -> resumes at offset 0.
    consumer.commit = original_commit  # type: ignore[method-assign]
    consumer.restart()
    writer2 = BronzeWriter(consumer, store, Batcher(3, 30), clock=Clock(), wall_clock_ms=lambda: 42)
    drain(writer2)

    assert len(store.objects) == 2                  # offset=0 overwritten, offset=3 added
    report = reconcile(store)["transactions"]
    assert report.rows == 6 and report.healthy      # 0..5 exactly once
    assert consumer.committed[(TOPIC, 0)] == 6


def test_storage_failure_commits_nothing() -> None:
    writer, consumer, store, _ = make([message(o) for o in range(3)])
    store.fail_next_put = True
    with pytest.raises(OSError):
        drain(writer)
    assert consumer.committed == {}                 # will be re-read: no loss


def test_shutdown_flushes_pending_rows() -> None:
    writer, consumer, store, _ = make([message(0), message(1)], max_records=100)
    drain(writer)
    assert store.objects == {}
    writer.shutdown()
    assert consumer.committed[(TOPIC, 0)] == 2


def test_reconcile_detects_gaps_and_duplicates() -> None:
    store = FakeStore()
    consumer = FakeConsumer([], store.events)
    w = BronzeWriter(consumer, store, Batcher(10, 30), clock=Clock(), wall_clock_ms=lambda: 0)
    for offsets in ([0, 1, 2], [2, 3], [6]):   # 2 twice, 4-5 missing
        b = Batcher(10, 30)
        for o in offsets:
            b.add(message(o), to_row(message(o), 0), 0)
        w.flush(b.drain()[0])
    p = reconcile(store)["transactions"].partitions[0]
    assert (p.rows, p.duplicates, p.gaps) == (5, 1, 2)


def test_batch_rejects_out_of_order_offsets() -> None:
    b = Batcher(10, 30)
    b.add(message(5), to_row(message(5), 0), 0)
    with pytest.raises(ValueError):
        b.add(message(4), to_row(message(4), 0), 0)
