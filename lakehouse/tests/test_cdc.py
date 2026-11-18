"""From raw CDC events to the current state of a table."""

from __future__ import annotations

from pyspark.sql import SparkSession

from bronze import Topic, account
from kaarangepay_lake.cdc import current_state, parse_changes
from kaarangepay_lake.schemas import ACCOUNTS_JSON


def state(spark: SparkSession, topic: Topic) -> dict[str, int]:
    parsed = parse_changes(topic.df(spark), ACCOUNTS_JSON)
    return {r["id"]: r["balance"] for r in current_state(parsed.changes, ["id"]).collect()}


def test_latest_update_wins(spark: SparkSession) -> None:
    t = Topic("accounts").change("r", account("A", 0)).change("u", account("A", 500)).change("u", account("A", 200))
    assert state(spark, t) == {"A": 200}


def test_snapshot_and_streaming_rows_are_both_kept(spark: SparkSession) -> None:
    t = Topic("accounts").change("r", account("A", 10)).change("c", account("B", 20))
    assert state(spark, t) == {"A": 10, "B": 20}


def test_delete_removes_the_key_and_its_tombstone_is_ignored(spark: SparkSession) -> None:
    t = (Topic("accounts").change("c", account("A", 10)).change("c", account("B", 20))
         .change("d", before={"id": "A"}).tombstone())
    assert state(spark, t) == {"B": 20}
    assert parse_changes(t.df(spark), ACCOUNTS_JSON).rejected.count() == 0  # tombstone is not an error


def test_key_recreated_after_delete_is_back(spark: SparkSession) -> None:
    t = Topic("accounts").change("c", account("A", 1)).change("d", before={"id": "A"}).change("c", account("A", 7))
    assert state(spark, t) == {"A": 7}


def test_order_is_the_kafka_offset_not_the_arrival_in_the_file(spark: SparkSession) -> None:
    t = Topic("accounts").change("c", account("A", 1)).change("u", account("A", 2))
    t.rows.reverse()  # files can be read in any order: only the offset matters
    assert state(spark, t) == {"A": 2}


def test_undecodable_payloads_are_rejected_and_counted(spark: SparkSession) -> None:
    t = Topic("accounts").change("c", account("A", 1)).raw("{not json").raw('{"op": "x", "after": {}}')
    parsed = parse_changes(t.df(spark), ACCOUNTS_JSON)
    assert parsed.changes.count() == 1
    assert parsed.rejected.count() == 2
