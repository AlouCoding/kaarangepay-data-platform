"""Ground-truth fraud labels.

A real operator learns about fraud later (customer complaint, investigation).
The generator knows it immediately and writes it to a JSONL file, which plays the
role of the "fraud investigations" feed. It will be ingested in phase 4 to train
and evaluate the fraud model. The payment API itself never sees these labels.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class FraudLabel:
    transaction_id: str
    scenario: str
    role: str  # e.g. "drain_transfer", "mule_cash_out"
    occurred_at: str


class LabelSink:
    """Thread-safe, append-only JSONL writer. ``path=None`` keeps labels in memory only."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.labels: list[FraudLabel] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, transaction_id: str, scenario: str, role: str, occurred_at: datetime) -> None:
        label = FraudLabel(transaction_id, scenario, role, occurred_at.isoformat())
        with self._lock:
            self.labels.append(label)
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(asdict(label)) + "\n")
