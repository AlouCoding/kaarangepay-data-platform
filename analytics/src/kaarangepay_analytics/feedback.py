"""Analyst decisions from the fraud console ("confirmed fraud" / "false positive").

Stored in a small SQLite file, separate from the DuckDB warehouse: the warehouse is rebuilt and swapped
by the pipeline, but human decisions must never be overwritten. In phase 5 they become training labels.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

DECISIONS = ("fraud", "false_positive")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS decisions ("
        " alert_id TEXT PRIMARY KEY, decision TEXT NOT NULL, decided_at TEXT NOT NULL)"
    )
    return con


def record(path: Path, alert_id: str, decision: str) -> None:
    """Last decision wins (an analyst may change their mind)."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
    with closing(_connect(path)) as con, con:
        con.execute(
            "INSERT INTO decisions VALUES (?, ?, ?) "
            "ON CONFLICT(alert_id) DO UPDATE SET decision = excluded.decision, decided_at = excluded.decided_at",
            (alert_id, decision, datetime.now(UTC).isoformat(timespec="seconds")),
        )


def all_decisions(path: Path) -> dict[str, str]:
    with closing(_connect(path)) as con:
        return dict(con.execute("SELECT alert_id, decision FROM decisions").fetchall())
