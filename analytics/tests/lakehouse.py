"""Writes a tiny but consistent lakehouse (silver Delta tables + gold alerts), with the same columns
as the Spark jobs produce. Story: the treasury tops up an agent, the agent cashes in Awa, Awa pays a
merchant, Awa is drained to a mule who cashes out, and one transfer fails."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pyarrow as pa
from deltalake import write_deltalake

UTC = dt.UTC
T0 = dt.datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
TREASURY, AGENT, AWA, SHOP, MULE = "acc-treasury", "acc-agent", "acc-awa", "acc-shop", "acc-mule"


def at(minutes: int) -> dt.datetime:
    return T0 + dt.timedelta(minutes=minutes)


TXS: list[tuple[str, str, str, str, int, int, str, int]] = [
    # id, type, source, destination, amount, fee, status, minute
    ("t1", "FLOAT_TOPUP", TREASURY, AGENT, 100_000, 0, "COMPLETED", 0),
    ("t2", "CASH_IN", AGENT, AWA, 60_000, 0, "COMPLETED", 10),
    ("t3", "PAYMENT", AWA, SHOP, 5_000, 0, "COMPLETED", 60),
    ("t4", "TRANSFER", AWA, MULE, 50_000, 500, "COMPLETED", 24 * 60),       # next day
    ("t5", "CASH_OUT", MULE, AGENT, 49_000, 245, "COMPLETED", 24 * 60 + 12),
    ("t6", "TRANSFER", AWA, SHOP, 90_000, 900, "FAILED", 24 * 60 + 30),
]

# account -> final balance (treasury pays nothing back: fees go to the FEES system account in reality;
# here fees are booked to the agent to keep the example short and balanced)
FEES = "acc-fees"


def ledger() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    n = 0
    for tx, _type, src, dst, amount, fee, status, minute in TXS:
        if status != "COMPLETED":
            continue
        for account, direction, value in [(src, "DEBIT", amount + fee), (dst, "CREDIT", amount), (FEES, "CREDIT", fee)]:
            if value == 0:
                continue
            n += 1
            signed = value if direction == "CREDIT" else -value
            rows.append({"id": n, "transaction_id": tx, "account_id": account, "direction": direction,
                         "amount": value, "balance_after": 0, "occurred_at": at(minute), "recorded_at": at(minute),
                         "signed_amount": signed, "occurred_date": at(minute).date()})
    return rows


def balances() -> dict[str, int]:
    out = {a: 0 for a in (TREASURY, AGENT, AWA, SHOP, MULE, FEES)}
    for row in ledger():
        out[row["account_id"]] += row["signed_amount"]
    return out


def write(root: Path, *, break_ledger: bool = False, with_alerts: bool = True) -> None:
    silver, gold = root / "silver", root / "gold"
    accounts = [{"id": a, "phone": f"+221{i}", "owner_name": a, "account_type": t, "status": "ACTIVE",
                 "currency": "XOF", "balance": b, "version": 0, "created_at": T0, "updated_at": T0}
                for i, (a, t, b) in enumerate(
                    (acc, "SYSTEM" if acc in (TREASURY, FEES) else
                     "AGENT" if acc == AGENT else "MERCHANT" if acc == SHOP else "CUSTOMER", bal)
                    for acc, bal in balances().items())]
    txs = [{"id": i, "idempotency_key": f"k-{i}", "transaction_type": ty, "status": st, "source_account_id": s,
            "destination_account_id": d, "amount": a, "fee": f, "currency": "XOF",
            "failure_reason": None if st == "COMPLETED" else "INSUFFICIENT_FUNDS",
            "occurred_at": at(m), "recorded_at": at(m) + dt.timedelta(milliseconds=40), "occurred_date": at(m).date()}
           for i, ty, s, d, a, f, st, m in TXS]
    entries = ledger()
    if break_ledger:
        entries = entries[:-1]   # one credit lost on the way
    write_deltalake(str(silver / "accounts"), pa.Table.from_pylist(accounts), mode="overwrite")
    write_deltalake(str(silver / "transactions"), pa.Table.from_pylist(txs), mode="overwrite")
    write_deltalake(str(silver / "ledger_entries"), pa.Table.from_pylist(entries), mode="overwrite")
    if with_alerts:
        alert = {"alert_id": "t5", "rule": "pass_through_mule", "account_id": MULE, "sender_account_id": AWA,
                 "transfer_id": "t4", "transfer_amount": 50_000, "transfer_at": at(24 * 60), "cashout_id": "t5",
                 "cashout_amount": 49_000, "cashout_at": at(24 * 60 + 12), "minutes_between": 12.0,
                 "detected_at": at(24 * 60 + 13)}
        # the at-least-once Kafka path can duplicate an alert: staging must dedupe it
        write_deltalake(str(gold / "fraud_alerts"), pa.Table.from_pylist([alert, alert]), mode="overwrite")
