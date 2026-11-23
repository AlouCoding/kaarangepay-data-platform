"""Load + dbt build + publish, end to end on a tiny lakehouse (real Delta tables, real dbt, real DuckDB)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

import lakehouse
from kaarangepay_analytics.config import Settings
from kaarangepay_analytics.pipeline import run_pipeline


def settings(root: Path) -> Settings:
    return Settings(silver_root=str(root / "silver"), gold_root=str(root / "gold"),
                    warehouse=root / "wh" / "kaarangepay.duckdb", feedback_db=root / "wh" / "fb.sqlite")


def query(path: Path, sql: str) -> list[tuple[object, ...]]:
    with duckdb.connect(str(path), read_only=True) as con:
        return con.execute(sql).fetchall()


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("lake")
    lakehouse.write(root)
    result = run_pipeline(settings(root))
    assert result.dbt_ok and result.published
    return settings(root).warehouse


def test_raw_tables_are_loaded_from_delta(built: Path) -> None:
    counts = dict(query(built, "select table_name, estimated_size from duckdb_tables() where schema_name = 'raw'"))
    assert set(counts) == {"accounts", "transactions", "ledger_entries", "fraud_alerts"}


def test_daily_kpis_count_completed_volume_and_fees(built: Path) -> None:
    rows = query(built, "select day, transactions, completed, volume_xof, fees_xof, flagged_fraud_tx "
                        "from marts.agg_daily_kpis order by day")
    assert [r[1:] for r in rows] == [(3, 3, 165_000, 0, 0), (3, 2, 99_000, 745, 2)]


def test_failure_rate_and_type_mix(built: Path) -> None:
    rate = query(built, "select failure_rate from marts.agg_daily_kpis order by day")
    assert [r[0] for r in rate] == [0.0, round(1 - 2 / 3, 4)]
    transfer = query(built, "select transactions, completed from marts.agg_by_type where transaction_type='TRANSFER'")
    assert transfer == [(2, 1)]


def test_duplicate_alert_is_deduplicated_and_marks_both_legs(built: Path) -> None:
    assert query(built, "select count(*) from marts.fct_fraud_alerts") == [(1,)]
    flagged = query(built, "select transaction_id from marts.fct_transactions where is_flagged_fraud order by 1")
    assert flagged == [("t4",), ("t5",)]
    mule = f"select fraud_alerts_as_mule from marts.dim_account where account_id = '{lakehouse.MULE}'"
    assert query(built, mule) == [(1,)]


def test_payday_and_weekday_come_from_the_calendar(built: Path) -> None:
    rows = query(built, "select day_name_fr, is_payday_period from marts.dim_date order by day")
    assert rows == [("Lundi", True), ("Mardi", True)]   # 2 and 3 November 2026: end-of-month salaries


def test_a_broken_ledger_is_not_published(tmp_path: Path) -> None:
    good = tmp_path / "good"
    lakehouse.write(good)
    conf = settings(good)
    assert run_pipeline(conf).published

    lakehouse.write(good, break_ledger=True)   # a credit lost between the lakehouse and the warehouse
    result = run_pipeline(conf)
    assert not result.dbt_ok and not result.published
    # the dashboard keeps the last correct warehouse: 12 ledger entries, not 11
    assert query(conf.warehouse, "select count(*) from raw.ledger_entries") == [(12,)]


def test_missing_alert_table_still_builds(tmp_path: Path) -> None:
    lakehouse.write(tmp_path, with_alerts=False)
    result = run_pipeline(settings(tmp_path))
    assert result.published
    assert query(settings(tmp_path).warehouse, "select count(*) from marts.fct_fraud_alerts") == [(0,)]
