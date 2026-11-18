"""HTTP client for payment-core, written the way a real mobile app should be:
every money movement carries an idempotency key, and network failures are
retried *with the same key* so a retry can never debit twice."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

TREASURY_ID = "00000000-0000-0000-0000-000000000001"


class PhoneAlreadyUsedError(Exception):
    """The phone number already has an account (payment-core enforces UNIQUE on phone)."""


@dataclass(frozen=True)
class TxResult:
    """Outcome of a POST /transactions call."""

    http_status: int
    transaction_id: str | None
    status: str | None  # COMPLETED | FAILED | None (rejected request)
    failure_reason: str | None
    replayed: bool

    @property
    def completed(self) -> bool:
        return self.status == "COMPLETED"


class PaymentApi(Protocol):
    """What the simulator needs. Implemented by ``HttpPaymentApi`` and by test fakes."""

    def open_account(self, phone: str, owner_name: str, account_type: str) -> str: ...

    def balance(self, account_id: str) -> int: ...

    def submit(
        self,
        idempotency_key: str,
        tx_type: str,
        source: str,
        destination: str,
        amount: int,
        occurred_at: datetime | None,
    ) -> TxResult: ...


class HttpPaymentApi:
    """``PaymentApi`` over HTTP, with retries on transient failures."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 10.0,
        max_retries: int = 4,
        backoff_s: float = 0.2,
        transport: httpx.BaseTransport | None = None,  # injectable for tests
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport)
        self._max_retries = max_retries
        self._backoff_s = backoff_s

    def close(self) -> None:
        self._http.close()

    def open_account(self, phone: str, owner_name: str, account_type: str) -> str:
        payload = {"phone": phone, "ownerName": owner_name, "type": account_type}
        response = self._request("POST", "/api/v1/accounts", json=payload)
        if response.status_code == 422 and "already exists" in response.text:
            raise PhoneAlreadyUsedError(phone)
        response.raise_for_status()
        return str(response.json()["id"])

    def balance(self, account_id: str) -> int:
        response = self._request("GET", f"/api/v1/accounts/{account_id}")
        response.raise_for_status()
        return int(response.json()["balance"])

    def submit(
        self,
        idempotency_key: str,
        tx_type: str,
        source: str,
        destination: str,
        amount: int,
        occurred_at: datetime | None,
    ) -> TxResult:
        headers = {"Idempotency-Key": idempotency_key}
        if occurred_at is not None:
            headers["X-Simulated-Time"] = occurred_at.isoformat()
        payload = {
            "type": tx_type,
            "sourceAccountId": source,
            "destinationAccountId": destination,
            "amount": amount,
        }
        response = self._request("POST", "/api/v1/transactions", json=payload, headers=headers)
        if response.status_code >= 500 or response.status_code in (400, 409):
            response.raise_for_status()
        body: dict[str, Any] = response.json()
        return TxResult(
            http_status=response.status_code,
            transaction_id=body.get("id"),
            status=body.get("status"),
            failure_reason=body.get("failureReason"),
            replayed=response.headers.get("Idempotent-Replay") == "true",
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Retries network errors and 5xx with exponential backoff.
        Safe for POST /transactions only because the idempotency key is reused."""
        delay = self._backoff_s
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.request(method, url, **kwargs)
                if response.status_code < 500 or attempt == self._max_retries:
                    return response
            except httpx.TransportError:
                if attempt == self._max_retries:
                    raise
            time.sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")
