"""Read side of the app: small, typed functions returning pandas DataFrames.

* Business view  -> the DuckDB warehouse built by dbt (refreshed by `analytics pipeline`).
* Fraud console  -> the gold Delta table written by the streaming job, read LIVE (no pipeline needed),
                    joined with the analysts' decisions.
Each call opens a short read-only connection: the pipeline can swap the warehouse file at any time.
"""

from __future__ import annotations

import duckdb
import pandas as pd
from deltalake import DeltaTable
from deltalake.exceptions import TableNotFoundError

from kaarangepay_analytics import feedback
from kaarangepay_analytics.config import Settings


def warehouse_ready(settings: Settings) -> bool:
    return settings.warehouse.exists()


def query(settings: Settings, sql: str) -> pd.DataFrame:
    with duckdb.connect(str(settings.warehouse), read_only=True) as con:
        frame: pd.DataFrame = con.execute(sql).df()
        return frame


def headline(settings: Settings) -> pd.Series:
    frame = query(settings, """
        select sum(transactions) as transactions, sum(volume_xof) as volume_xof, sum(fees_xof) as fees_xof,
               1 - sum(completed) / sum(transactions) as failure_rate,
               (select count(*) from marts.dim_account where account_type = 'CUSTOMER') as customers,
               (select count(*) from marts.fct_fraud_alerts) as fraud_alerts,
               min(day) as first_day, max(day) as last_day
        from marts.agg_daily_kpis""")
    return frame.iloc[0]


def daily(settings: Settings) -> pd.DataFrame:
    return query(settings, "select * from marts.agg_daily_kpis order by day")


def by_type(settings: Settings) -> pd.DataFrame:
    return query(settings, "select * from marts.agg_by_type order by volume_xof desc")


def by_hour(settings: Settings) -> pd.DataFrame:
    return query(settings, "select * from marts.agg_activity_by_hour")


ALERT_COLUMNS = ["alert_id", "victim_account_id", "mule_account_id", "transfer_id", "transfer_amount_xof",
                 "transfer_at", "cashout_id", "cashout_amount_xof", "cashout_at", "minutes_between",
                 "detected_at", "decision"]


def live_alerts(settings: Settings) -> pd.DataFrame:
    """Latest fraud alerts straight from gold (Delta), newest first, with the analyst decision if any."""
    uri = f"{settings.gold_root}/fraud_alerts"
    try:
        table = DeltaTable(uri, storage_options=settings.storage_options(uri))
    except TableNotFoundError:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    raw = table.to_pyarrow_table(engine="datafusion").to_pandas()
    if raw.empty:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    alerts = (raw.drop_duplicates("alert_id")      # Kafka path is at-least-once: same id = same alert
              .rename(columns={"sender_account_id": "victim_account_id", "account_id": "mule_account_id",
                               "transfer_amount": "transfer_amount_xof", "cashout_amount": "cashout_amount_xof"}))
    decisions = feedback.all_decisions(settings.feedback_db)
    alerts["decision"] = [decisions.get(a, "pending") for a in alerts["alert_id"]]
    ordered: pd.DataFrame = alerts.sort_values("cashout_at", ascending=False)[ALERT_COLUMNS]
    return ordered.reset_index(drop=True)


NARROW_NBSP = chr(0x202F)   # French thousands separator: 12 345 678


def thousands(value: float | int) -> str:
    return f"{round(value):,}".replace(",", NARROW_NBSP)


def xof(value: float | int) -> str:
    return thousands(value) + " XOF"


def xof_short(value: float | int) -> str:
    """Compact amount for KPI cards (the unit is in the label): 3,2 Md / 845,2 M / 12,5 k."""
    for size, unit in ((1e9, "Md"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= size:
            return f"{value / size:.1f}".replace(".", ",") + f" {unit}"
    return thousands(value)
