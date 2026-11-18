"""The pass-through rule (batch and streaming) and its evaluation against labels."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import LongType, StringType, StructField, StructType, TimestampType

from kaarangepay_lake.fraud import evaluate, pass_through_alerts

TX = StructType([
    StructField("id", StringType()), StructField("transaction_type", StringType()),
    StructField("status", StringType()), StructField("source_account_id", StringType()),
    StructField("destination_account_id", StringType()), StructField("amount", LongType()),
    StructField("occurred_at", TimestampType()),
])
T0 = dt.datetime(2026, 11, 18, 10, 0)


Row = dict[str, Any]


def tx(id_: str, type_: str, src: str, dst: str, amount: int, minute: float, status: str = "COMPLETED") -> Row:
    return {"id": id_, "transaction_type": type_, "status": status, "source_account_id": src,
            "destination_account_id": dst, "amount": amount, "occurred_at": T0 + dt.timedelta(minutes=minute)}


def takeover(n: str, minute: float = 0, delay: float = 10, ratio: float = 0.995, amount: int = 100_000) -> list[Row]:
    """victim-n drains its wallet to mule-n, who cashes out `ratio` of it `delay` minutes later."""
    return [tx(f"drain-{n}", "TRANSFER", f"victim-{n}", f"mule-{n}", amount, minute),
            tx(f"cash-{n}", "CASH_OUT", f"mule-{n}", "agent", int(amount * ratio), minute + delay)]


def alerts(spark: SparkSession, rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(r["transfer_id"], r["cashout_id"]) for r in pass_through_alerts(spark.createDataFrame(rows, TX)).collect()}


def test_the_mule_pattern_raises_one_alert(spark: SparkSession) -> None:
    assert alerts(spark, takeover("1")) == {("drain-1", "cash-1")}


def test_cash_out_too_late_is_not_the_pattern(spark: SparkSession) -> None:
    assert alerts(spark, takeover("1", delay=45)) == set()


def test_partial_cash_out_is_not_the_pattern(spark: SparkSession) -> None:
    assert alerts(spark, takeover("1", ratio=0.5)) == set()


def test_cash_out_before_the_transfer_is_not_the_pattern(spark: SparkSession) -> None:
    assert alerts(spark, takeover("1", delay=-5)) == set()


def test_small_transfers_and_failed_cash_outs_are_ignored(spark: SparkSession) -> None:
    small = takeover("1", amount=2_000)
    failed = takeover("2")
    failed[1]["status"] = "FAILED"
    assert alerts(spark, small + failed) == set()


def test_cash_out_by_another_account_does_not_match(spark: SparkSession) -> None:
    rows = takeover("1")
    rows[1]["source_account_id"] = "someone-else"
    assert alerts(spark, rows) == set()


def test_same_rule_runs_on_a_stream_with_a_watermark(spark: SparkSession, tmp_path: Path) -> None:
    """Streaming path: files arrive as micro-batches, Spark joins them with bounded state."""
    source = tmp_path / "in"
    source.mkdir()
    batches = [takeover("1", minute=0)[:1], takeover("1", minute=0)[1:] + takeover("2", minute=60)]
    for i, batch in enumerate(batches):  # the transfer and its cash-out arrive in different files
        lines = [json.dumps({**r, "occurred_at": r["occurred_at"].isoformat()}) for r in batch]
        (source / f"batch-{i}.json").write_text("\n".join(lines))

    stream = spark.readStream.schema(TX).option("maxFilesPerTrigger", 1).json(str(source))
    query = (pass_through_alerts(stream.withWatermark("occurred_at", "45 minutes"))
             .writeStream.format("memory").queryName("alerts_test").outputMode("append")
             .option("checkpointLocation", str(tmp_path / "chk")).trigger(availableNow=True).start())
    query.awaitTermination()
    found = {(r["transfer_id"], r["cashout_id"]) for r in spark.table("alerts_test").collect()}
    assert found == {("drain-1", "cash-1"), ("drain-2", "cash-2")}


def test_evaluation_counts_precision_and_recall(spark: SparkSession) -> None:
    rows = takeover("1") + takeover("2") + [
        tx("t-legit", "TRANSFER", "awa", "momar", 50_000, 0),      # honest: Momar cashes out right after
        tx("c-legit", "CASH_OUT", "momar", "agent", 49_000, 5),
    ] + takeover("3", ratio=0.5)                                    # a fraud the rule misses
    txs: DataFrame = spark.createDataFrame(rows, TX)
    found = pass_through_alerts(txs)
    labels = spark.createDataFrame(
        [(f"drain-{n}", "drain_transfer") for n in "123"] + [(f"cash-{n}", "mule_cash_out") for n in "123"]
        + [("from-an-old-database", "drain_transfer")],
        ["transaction_id", "role"])
    result = evaluate(found, labels, txs)
    assert (result.labelled, result.flagged, result.true_positives) == (6, 6, 4)
    assert (result.cases, result.cases_detected) == (3, 2)
    assert round(result.precision, 3) == 0.667 and round(result.recall, 3) == 0.667
