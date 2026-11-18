"""Generic CDC logic: from bronze rows (raw Debezium envelopes) to the current state of a table.

Two steps, both pure DataFrame -> DataFrame functions (easy to unit-test):

1. `parse_changes`: decode the JSON envelope and keep the row image.
   - create / snapshot / update (`c`, `r`, `u`) -> the `after` image
   - delete (`d`)                               -> the `before` image (at least the primary key)
   Rows whose payload cannot be decoded are returned separately (`rejected`): bronze accepts
   everything, silver decides — and counts what it refuses instead of hiding it.

2. `current_state`: keep the **latest version of each primary key**, then drop deleted keys.
   Ordering by Kafka offset is safe: Debezium uses the primary key as the Kafka key, so every
   version of a row lands in the same partition, in commit order.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType

#: Technical columns added next to the business columns (prefixed with `_`).
CDC_COLUMNS = ["_cdc_op", "_source_lsn", "_kafka_partition", "_kafka_offset", "_debezium_ts_ms"]


def envelope_schema(row_schema: StructType) -> StructType:
    """The part of a Debezium envelope that silver needs."""
    return StructType([
        StructField("before", row_schema, True),
        StructField("after", row_schema, True),
        StructField("op", StringType(), True),
        StructField("ts_ms", LongType(), True),
    ])


@dataclass(frozen=True)
class ParsedChanges:
    changes: DataFrame   # one row per change event: business columns + CDC_COLUMNS
    rejected: DataFrame  # bronze rows that could not be interpreted


def parse_changes(bronze: DataFrame, row_schema: StructType) -> ParsedChanges:
    env = F.from_json(F.col("payload"), envelope_schema(row_schema))
    decoded = bronze.withColumn("_env", env)

    image: Column = F.when(F.col("_env.op") == "d", F.col("_env.before")).otherwise(F.col("_env.after"))
    is_valid = (
        F.col("payload").isNotNull()
        & F.col("_env.op").isin("c", "r", "u", "d")
        & F.col("_image").isNotNull()
    )
    with_image = decoded.withColumn("_image", image)

    changes = with_image.where(is_valid).select(
        *[F.col(f"_image.{f.name}").alias(f.name) for f in row_schema.fields],
        F.col("_env.op").alias("_cdc_op"),
        F.col("source_lsn").alias("_source_lsn"),
        F.col("kafka_partition").alias("_kafka_partition"),
        F.col("kafka_offset").alias("_kafka_offset"),
        F.col("_env.ts_ms").alias("_debezium_ts_ms"),
    )
    # Tombstones (payload = null) follow every delete: they are expected, not errors.
    rejected = with_image.where(~is_valid & F.col("payload").isNotNull()).drop("_env", "_image")
    return ParsedChanges(changes=changes, rejected=rejected)


def current_state(changes: DataFrame, keys: list[str]) -> DataFrame:
    """Latest version of each key; deleted keys disappear."""
    latest_first = Window.partitionBy(*keys).orderBy(F.col("_kafka_offset").desc())
    return (
        changes.withColumn("_rank", F.row_number().over(latest_first))
        .where((F.col("_rank") == 1) & (F.col("_cdc_op") != "d"))
        .drop("_rank")
    )
