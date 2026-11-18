"""Real-time fraud rule: the *pass-through* (money mule) pattern.

Account takeover in mobile money (and in PaySim) looks like this:

    victim --TRANSFER (almost the whole balance)--> mule --CASH_OUT (almost all of it, minutes later)--> agent

A velocity rule ("too many transactions in 10 minutes") would not see it: the mule makes only
two moves. What gives it away is the **link** between the two moves: money that comes in and
goes out as cash, nearly in full, within a short delay. That is a join between two events of the
same stream, on the mule's account, bounded in time.

`pass_through_alerts` is a pure DataFrame function: the same code runs on a batch DataFrame (tests)
and on a streaming one (Kafka), where Spark keeps the join state and drops it once the watermark
passes the time bound.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dataclass(frozen=True)
class PassThroughRule:
    window_minutes: int = 30      # cash-out must follow the incoming transfer within this delay
    min_ratio: float = 0.9        # ... and take at least 90% of it out
    min_amount: int = 5_000       # ignore small transfers (XOF)


RULE_NAME = "pass_through_mule"


def pass_through_alerts(transactions: DataFrame, rule: PassThroughRule = PassThroughRule()) -> DataFrame:
    """One alert per (incoming TRANSFER, CASH_OUT) pair matching the rule.

    `transactions` needs: id, transaction_type, status, source_account_id,
    destination_account_id, amount, occurred_at (TIMESTAMP, event time).
    """
    done = transactions.where(F.col("status") == "COMPLETED")
    incoming = done.where(
        (F.col("transaction_type") == "TRANSFER") & (F.col("amount") >= rule.min_amount)
    ).select(
        F.col("id").alias("transfer_id"),
        F.col("source_account_id").alias("sender_account_id"),
        F.col("destination_account_id").alias("t_account_id"),
        F.col("amount").alias("transfer_amount"),
        F.col("occurred_at").alias("transfer_at"),
    )
    cash_outs = done.where(F.col("transaction_type") == "CASH_OUT").select(
        F.col("id").alias("cashout_id"),
        F.col("source_account_id").alias("c_account_id"),
        F.col("amount").alias("cashout_amount"),
        F.col("occurred_at").alias("cashout_at"),
    )
    window = F.expr(f"INTERVAL {rule.window_minutes} MINUTES")
    # Join condition = key + TIME bound only. Spark analyses this condition to know when it may drop
    # state; an amount comparison inside it made Spark log a (harmless) INTERNAL_ERROR at every
    # micro-batch. For an inner join, filtering the amounts right after the join gives the same rows.
    joined = incoming.join(
        cash_outs,
        (F.col("t_account_id") == F.col("c_account_id"))
        & (F.col("cashout_at") >= F.col("transfer_at"))
        & (F.col("cashout_at") <= F.col("transfer_at") + window),       # time bound: lets Spark drop state
        "inner",
    ).where(
        (F.col("cashout_amount") >= F.col("transfer_amount") * rule.min_ratio)
        & (F.col("cashout_amount") <= F.col("transfer_amount"))
    )
    return joined.select(
        F.col("cashout_id").alias("alert_id"),   # deterministic: a replay produces the same id
        F.lit(RULE_NAME).alias("rule"),
        F.col("t_account_id").alias("account_id"),
        "sender_account_id", "transfer_id", "transfer_amount", "transfer_at",
        "cashout_id", "cashout_amount", "cashout_at",
        ((F.unix_timestamp("cashout_at") - F.unix_timestamp("transfer_at")) / 60).alias("minutes_between"),
        F.current_timestamp().alias("detected_at"),
    )


@dataclass(frozen=True)
class Evaluation:
    labelled: int          # fraudulent transactions known to the lake (labels joined to silver)
    flagged: int           # transactions named by at least one alert
    true_positives: int
    cases: int             # fraud cases (drain transfers)
    cases_detected: int

    @property
    def precision(self) -> float:
        return self.true_positives / self.flagged if self.flagged else 0.0

    @property
    def recall(self) -> float:
        return self.true_positives / self.labelled if self.labelled else 0.0

    @property
    def case_recall(self) -> float:
        return self.cases_detected / self.cases if self.cases else 0.0


def evaluate(alerts: DataFrame, labels: DataFrame, transactions: DataFrame) -> Evaluation:
    """Compares alerts with the generator's ground truth.

    Labels whose transaction is not in silver are ignored (the label file is append-only and can
    hold labels of an older database). A transaction is *flagged* if an alert names it, as the
    transfer or as the cash-out.
    """
    known = labels.join(transactions.select("id"), labels["transaction_id"] == transactions["id"], "left_semi")
    flagged = (alerts.select(F.col("transfer_id").alias("tx"))
               .union(alerts.select(F.col("cashout_id").alias("tx"))).distinct())
    tp = flagged.join(known, flagged["tx"] == known["transaction_id"], "left_semi")
    drains = known.where(F.col("role") == "drain_transfer")
    detected = drains.join(alerts, drains["transaction_id"] == alerts["transfer_id"], "left_semi")
    return Evaluation(
        labelled=int(known.select("transaction_id").distinct().count()),
        flagged=int(flagged.count()),
        true_positives=int(tp.count()),
        cases=int(drains.count()),
        cases_detected=int(detected.count()),
    )
