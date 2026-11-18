"""Spark Structured Streaming job: Kafka -> pass-through rule -> alerts (Kafka topic + gold Delta table).

    kaarangepay.public.transactions (Kafka, Debezium JSON)
        -> decode the envelope (same code as silver: cdc.parse_changes)
        -> event time = occurred_at, watermark
        -> pass_through_alerts (stream-stream join, state bounded by the watermark)
        -> kaarangepay.fraud.alerts (Kafka)     for the real-time consumers
        -> s3a://gold/fraud_alerts (Delta)      for analysis and evaluation

Each sink has its own **checkpoint** on S3: Kafka offsets read + join state. After a crash the query
restarts from the checkpoint: nothing is skipped, and the Delta sink writes each micro-batch once.
"""

from __future__ import annotations

from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from kaarangepay_lake.cdc import parse_changes
from kaarangepay_lake.fraud import PassThroughRule, pass_through_alerts
from kaarangepay_lake.silver import TABLES

#: Why 45 minutes: in backfill mode the generator submits a mule's cash-out right after the drain
#: transfer but with an event time up to 30 min LATER. That pushes the max event time seen forward by
#: up to 30 min; a shorter watermark would then declare the following normal events "late" and drop them.
WATERMARK = "45 minutes"


def transactions_stream(spark: SparkSession, bootstrap: str, topic: str) -> DataFrame:
    raw = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("maxOffsetsPerTrigger", 50_000)   # bounded micro-batches when catching up
        .load()
    )
    # Shape the Kafka record like a bronze row, so the decoding code is shared with silver.
    as_bronze = raw.select(
        F.col("value").cast("string").alias("payload"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        F.lit(None).cast("long").alias("source_lsn"),
    )
    table = TABLES["transactions"]
    changes = parse_changes(as_bronze, table.json_schema).changes
    # transactions are insert-only: c (create) and r (snapshot) only
    return table.typed(changes.where(F.col("_cdc_op").isin("c", "r")))


def start(spark: SparkSession, bootstrap: str, source_topic: str, alerts_topic: str,
          gold_root: str, once: bool) -> list[object]:
    alerts = pass_through_alerts(transactions_stream(spark, bootstrap, source_topic).withWatermark(
        "occurred_at", WATERMARK), PassThroughRule())

    def trigger(writer: Any) -> Any:
        return writer.trigger(availableNow=True) if once else writer.trigger(processingTime="10 seconds")

    to_delta = trigger(
        alerts.writeStream.format("delta").outputMode("append")
        .option("checkpointLocation", f"{gold_root}/_checkpoints/fraud_alerts_delta")
    ).start(f"{gold_root}/fraud_alerts")

    to_kafka = trigger(
        alerts.select(F.col("alert_id").alias("key"), F.to_json(F.struct("*")).alias("value"))
        .writeStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("topic", alerts_topic)
        .option("checkpointLocation", f"{gold_root}/_checkpoints/fraud_alerts_kafka")
    ).start()
    return [to_delta, to_kafka]
