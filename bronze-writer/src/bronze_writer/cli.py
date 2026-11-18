"""Entry point: `bronze-writer run` and `bronze-writer reconcile`. Configured by environment."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time

from bronze_writer.batching import Batcher
from bronze_writer.reconcile import reconcile
from bronze_writer.storage import S3Store
from bronze_writer.writer import BronzeWriter

log = logging.getLogger("bronze_writer")

DEFAULT_TOPICS = ("kaarangepay.public.accounts,kaarangepay.public.transactions,"
                  "kaarangepay.public.ledger_entries")


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def store_from_env() -> S3Store:
    return S3Store(
        endpoint_url=env("S3_ENDPOINT", "http://seaweedfs:8333"),
        bucket=env("S3_BUCKET", "bronze"),
        access_key=env("S3_ACCESS_KEY", "bronze"),
        secret_key=env("S3_SECRET_KEY", "bronze-secret"),
    )


def wait_for_bucket(store: S3Store, attempts: int = 30) -> None:
    for attempt in range(1, attempts + 1):
        try:
            store.ensure_bucket()
            return
        except Exception as exc:  # storage may still be starting
            log.info("storage not ready (%d/%d): %s", attempt, attempts, exc)
            time.sleep(2)
    raise RuntimeError("object storage unreachable")


def run() -> None:
    from bronze_writer.kafka_adapter import KafkaConsumer

    store = store_from_env()
    wait_for_bucket(store)
    batcher = Batcher(int(env("BATCH_MAX_RECORDS", "5000")), float(env("BATCH_MAX_SECONDS", "30")))
    consumer = KafkaConsumer(env("KAFKA_BOOTSTRAP", "kafka:9092"), env("GROUP_ID", "bronze-writer"),
                             env("TOPICS", DEFAULT_TOPICS).split(","), batcher)
    writer = BronzeWriter(consumer, store, batcher)

    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("bronze-writer started")
    try:
        while not stopping:
            writer.step()
    finally:
        writer.shutdown()
        consumer.close()
        log.info("stopped: %d files, rows %s", writer.files_written, dict(writer.rows_written))


def report() -> None:
    reports = reconcile(store_from_env())
    if not reports:
        print("bronze is empty")
        return
    for table, rep in sorted(reports.items()):
        status = "OK" if rep.healthy else "PROBLEM"
        print(f"{table:<16} rows={rep.rows:>9,}  files={rep.files:>4}  [{status}]")
        for partition, p in sorted(rep.partitions.items()):
            print(f"    partition {partition}: rows={p.rows:,} offsets {p.min_offset}-{p.max_offset}"
                  f"  duplicates={p.duplicates} gaps={p.gaps}")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("botocore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="bronze-writer")
    parser.add_argument("command", choices=["run", "reconcile"])
    args = parser.parse_args(argv)
    run() if args.command == "run" else report()


if __name__ == "__main__":
    main()
