"""In-memory stand-in for payment-core, with the same business rules (fees, funds, idempotency)."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime

from mmgen.client import TREASURY_ID, TxResult

FEE_BPS = {"TRANSFER": 100, "CASH_OUT": 50}
MAX_FEE = 5_000


class FakePaymentApi:
    def __init__(self) -> None:
        self.balances: dict[str, int] = {TREASURY_ID: 0, "FEES": 0}
        self.types: dict[str, str] = {TREASURY_ID: "SYSTEM"}
        self.by_key: dict[str, tuple[tuple[object, ...], TxResult]] = {}
        self.occurred_at: dict[str, datetime | None] = {}
        self._lock = threading.Lock()

    def open_account(self, phone: str, owner_name: str, account_type: str) -> str:
        account_id = str(uuid.uuid4())
        with self._lock:
            self.balances[account_id] = 0
            self.types[account_id] = account_type
        return account_id

    def balance(self, account_id: str) -> int:
        return self.balances[account_id]

    def submit(self, idempotency_key: str, tx_type: str, source: str, destination: str,
               amount: int, occurred_at: datetime | None) -> TxResult:
        payload = (tx_type, source, destination, amount)
        with self._lock:
            if idempotency_key in self.by_key:
                stored_payload, stored = self.by_key[idempotency_key]
                assert stored_payload == payload, "key reused with another payload"
                return TxResult(200, stored.transaction_id, stored.status, stored.failure_reason, True)

            fee = min(amount * FEE_BPS.get(tx_type, 0) // 10_000, MAX_FEE)
            tx_id = str(uuid.uuid4())
            if self.types[source] != "SYSTEM" and self.balances[source] < amount + fee:
                result = TxResult(422, tx_id, "FAILED", "INSUFFICIENT_FUNDS", False)
            else:
                self.balances[source] -= amount + fee
                self.balances[destination] += amount
                self.balances["FEES"] += fee
                result = TxResult(201, tx_id, "COMPLETED", None, False)
            self.by_key[idempotency_key] = (payload, result)
            self.occurred_at[tx_id] = occurred_at
            return result
