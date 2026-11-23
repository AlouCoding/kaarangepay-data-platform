"""Smoke tests of the two Streamlit pages on a real (tiny) warehouse: they render without error and
show the right numbers; an analyst decision is stored and survives a pipeline rebuild."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import lakehouse
from kaarangepay_analytics import data, feedback
from kaarangepay_analytics.config import Settings
from kaarangepay_analytics.pipeline import run_pipeline

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Settings]:
    root = tmp_path_factory.mktemp("app")
    lakehouse.write(root)
    mp = pytest.MonkeyPatch()
    mp.setenv("SILVER_URI", str(root / "silver"))
    mp.setenv("GOLD_URI", str(root / "gold"))
    mp.setenv("WAREHOUSE_PATH", str(root / "wh" / "kaarangepay.duckdb"))
    mp.setenv("FEEDBACK_DB", str(root / "wh" / "feedback.sqlite"))
    settings = Settings()
    assert run_pipeline(settings).published
    yield settings
    mp.undo()


def test_business_page_shows_the_kpis(env: Settings) -> None:
    at = AppTest.from_file(str(APP / "views" / "business.py"), default_timeout=60).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Transactions"] == "6"
    assert metrics["Taux d'échec"] == "16.7%"
    assert metrics["Alertes fraude"] == "1"


def test_fraud_console_lists_live_alerts(env: Settings) -> None:
    at = AppTest.from_file(str(APP / "views" / "fraud.py"), default_timeout=60).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert (metrics["Alertes"], metrics["À traiter"]) == ("1", "1")   # the duplicated alert counts once


def test_decision_is_kept_across_rebuilds(env: Settings) -> None:
    feedback.record(env.feedback_db, "t5", "fraud")
    assert run_pipeline(env).published               # warehouse swapped...
    alerts = data.live_alerts(env)
    assert alerts.loc[0, "decision"] == "fraud"     # ...but the human decision is still there
    with pytest.raises(ValueError):
        feedback.record(env.feedback_db, "t5", "maybe")
