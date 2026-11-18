"""Proves the bronze layer is complete: per partition, offsets 0..N-1 exactly once.

Insert-only tables (transactions, ledger_entries) can then be compared with PostgreSQL:
rows in bronze = messages in Kafka = rows in the table.
"""

from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass, field

import pyarrow.parquet as pq

from bronze_writer.storage import ObjectStore


@dataclass
class PartitionReport:
    rows: int = 0
    min_offset: int | None = None
    max_offset: int | None = None
    duplicates: int = 0
    gaps: int = 0


@dataclass
class TableReport:
    files: int = 0
    partitions: dict[int, PartitionReport] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        return sum(p.rows for p in self.partitions.values())

    @property
    def healthy(self) -> bool:
        return all(p.duplicates == 0 and p.gaps == 0 for p in self.partitions.values())


def reconcile(store: ObjectStore) -> dict[str, TableReport]:
    offsets: dict[tuple[str, int], list[int]] = defaultdict(list)
    files: dict[str, int] = defaultdict(int)
    for key in store.list_keys():
        if not key.endswith(".parquet"):
            continue
        table_name = key.split("/", 1)[0]
        files[table_name] += 1
        columns = pq.read_table(io.BytesIO(store.get(key)), columns=["kafka_partition", "kafka_offset"])
        for partition, offset in zip(columns["kafka_partition"].to_pylist(),
                                     columns["kafka_offset"].to_pylist(), strict=True):
            if partition is not None and offset is not None:
                offsets[(table_name, int(partition))].append(int(offset))

    reports: dict[str, TableReport] = {t: TableReport(files=n) for t, n in files.items()}
    for (table_name, partition), values in offsets.items():
        values.sort()
        unique = sorted(set(values))
        report = PartitionReport(
            rows=len(unique),
            min_offset=unique[0],
            max_offset=unique[-1],
            duplicates=len(values) - len(unique),
            # Debezium topics are not compacted: offsets must be contiguous from the first one.
            gaps=(unique[-1] - unique[0] + 1) - len(unique),
        )
        reports[table_name].partitions[partition] = report
    return reports
