from datetime import UTC, datetime

import httpx

from mmgen.client import HttpPaymentApi


def test_retries_server_errors_with_the_same_idempotency_key() -> None:
    seen_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_keys.append(request.headers["Idempotency-Key"])
        if len(seen_keys) < 3:
            return httpx.Response(503)
        return httpx.Response(
            201,
            json={"id": "tx-1", "status": "COMPLETED", "failureReason": None},
            headers={"Idempotent-Replay": "false"},
        )

    api = HttpPaymentApi("http://test", backoff_s=0, transport=httpx.MockTransport(handler))
    result = api.submit("key-123", "TRANSFER", "a", "b", 1_000, None)

    assert result.completed
    assert seen_keys == ["key-123"] * 3


def test_sends_simulated_time_and_reads_failures() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(
            422,
            json={"id": "tx-2", "status": "FAILED", "failureReason": "INSUFFICIENT_FUNDS"},
            headers={"Idempotent-Replay": "true"},
        )

    api = HttpPaymentApi("http://test", transport=httpx.MockTransport(handler))
    result = api.submit("k", "TRANSFER", "a", "b", 1_000, datetime(2026, 11, 30, 18, 45, tzinfo=UTC))

    assert captured["x-simulated-time"] == "2026-11-30T18:45:00+00:00"
    assert result.status == "FAILED"
    assert result.failure_reason == "INSUFFICIENT_FUNDS"
    assert result.replayed
