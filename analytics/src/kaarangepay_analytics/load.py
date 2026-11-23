"""Extract: copy the silver Delta tables (and the gold fraud alerts) into DuckDB, schema `raw`.

Why not read the Parquet files directly? Silver is a *Delta* table: after each rebuild, old Parquet
files stay on S3 until vacuum. Only the transaction log (_delta_log) says which files are current.
delta-rs reads that log, so we get exactly the latest version, never a mix of old and new files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa
from deltalake import DeltaTable
from deltalake.exceptions import TableNotFoundError

from kaarangepay_analytics.config import Settings

SILVER_TABLES = ("accounts", "transactions", "ledger_entries")

#: Gold alerts may not exist yet (fraud job never run): dbt still needs the table, so we create it empty.
EMPTY_ALERTS = pa.schema([
    ("alert_id", pa.string()), ("rule", pa.string()), ("account_id", pa.string()),
    ("sender_account_id", pa.string()), ("transfer_id", pa.string()), ("transfer_amount", pa.int64()),
    ("transfer_at", pa.timestamp("us", tz="UTC")), ("cashout_id", pa.string()), ("cashout_amount", pa.int64()),
    ("cashout_at", pa.timestamp("us", tz="UTC")), ("minutes_between", pa.float64()),
    ("detected_at", pa.timestamp("us", tz="UTC")),
])


@dataclass(frozen=True)
class Loaded:
    table: str
    rows: int
    version: int | None   # Delta version read (None = table absent, loaded empty)


def read_delta(uri: str, settings: Settings) -> tuple[pa.Table, int]:
    table = DeltaTable(uri, storage_options=settings.storage_options(uri))
    return table.to_pyarrow_table(engine="datafusion"), table.version()


def load_raw(settings: Settings, target: Path) -> list[Loaded]:
    """Writes raw.<table> into the DuckDB file `target` (replaced table by table)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    loaded: list[Loaded] = []
    with duckdb.connect(str(target)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        sources = [(name, f"{settings.silver_root}/{name}") for name in SILVER_TABLES]
        sources.append(("fraud_alerts", f"{settings.gold_root}/fraud_alerts"))
        for name, uri in sources:
            try:
                data, version = read_delta(uri, settings)
            except TableNotFoundError:
                if name != "fraud_alerts":
                    raise
                data, version = EMPTY_ALERTS.empty_table(), None
            con.register("incoming", data)
            con.execute(f"CREATE OR REPLACE TABLE raw.{name} AS SELECT * FROM incoming")
            con.unregister("incoming")
            loaded.append(Loaded(name, data.num_rows, version))
    return loaded
