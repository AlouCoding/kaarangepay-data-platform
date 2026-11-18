import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fake_api import FakePaymentApi

from mmgen.client import TREASURY_ID
from mmgen.labels import LabelSink
from mmgen.simulator import (
    AMOUNT_PROFILE,
    MAX_AMOUNT,
    MIN_AMOUNT,
    Simulator,
    affordable_amount,
    build_population,
    fee_for,
    sample_amount,
)

TS = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def make_sim(tmp_path: Path | None = None, **kwargs: float) -> tuple[Simulator, FakePaymentApi]:
    api = FakePaymentApi()
    rng = random.Random(3)
    population = build_population(api, rng, n_customers=200, n_merchants=10, n_agents=5, start=TS)
    labels = LabelSink(tmp_path / "labels.jsonl" if tmp_path else None)
    return Simulator(api, population, labels, **kwargs), api


def total_money(api: FakePaymentApi) -> int:
    return sum(api.balances.values())


def test_amounts_are_rounded_and_bounded() -> None:
    rng = random.Random(0)
    for tx_type in AMOUNT_PROFILE:
        amounts = [sample_amount(tx_type, rng) for _ in range(2_000)]
        assert all(MIN_AMOUNT <= a <= MAX_AMOUNT and a % 25 == 0 for a in amounts)


def test_payments_are_smaller_than_cash_ins_on_median() -> None:
    rng = random.Random(0)
    payments = sorted(sample_amount("PAYMENT", rng) for _ in range(2_001))
    cash_ins = sorted(sample_amount("CASH_IN", rng) for _ in range(2_001))
    assert payments[1_000] < cash_ins[1_000]


def test_population_is_funded_and_has_mules() -> None:
    sim, api = make_sim()
    assert len(sim.pop.mules) == 2
    assert all(api.balance(c) > 0 for c in sim.pop.customers)
    assert all(api.balance(a) > 0 for a in sim.pop.agents)


def test_simulation_never_creates_money() -> None:
    sim, api = make_sim(duplicate_rate=0.05)
    for i in range(3_000):
        sim.step(TS, random.Random(i))
    # TREASURY is negative by exactly the e-money in circulation: the total is always 0.
    assert total_money(api) == 0
    assert api.balances[TREASURY_ID] < 0
    assert all(b >= 0 for acc, b in api.balances.items() if acc != TREASURY_ID)
    assert sim.stats.replays > 0
    assert sim.stats.by_type_status["PAYMENT:COMPLETED"] > 0


def test_agents_get_refilled_when_out_of_float() -> None:
    sim, api = make_sim()
    for agent in sim.pop.agents:
        api.balances[TREASURY_ID] += api.balances[agent]  # empty every agent, keep total at 0
        api.balances[agent] = 0
    for i in range(500):
        sim.step(TS, random.Random(i))
    assert sim.stats.agent_topups > 0


def test_account_takeover_drains_victim_then_mule_cashes_out(tmp_path: Path) -> None:
    sim, api = make_sim(tmp_path)
    sim.account_takeover(TS, random.Random(11))

    assert sim.stats.fraud_cases == 1
    roles = [label.role for label in sim.labels.labels]
    assert roles == ["drain_transfer", "mule_cash_out"]

    cash_out_id = sim.labels.labels[1].transaction_id
    cash_out_time = api.occurred_at[cash_out_id]
    assert cash_out_time is not None and cash_out_time > TS  # happens minutes later

    lines = (tmp_path / "labels.jsonl").read_text().splitlines()
    assert [json.loads(line)["role"] for line in lines] == roles


def test_fraud_rate_controls_frequency() -> None:
    sim, _ = make_sim(fraud_rate=1.0)
    for i in range(20):
        sim.step(TS, random.Random(i))
    assert sim.stats.fraud_cases > 0
    assert len(sim.labels.labels) >= sim.stats.fraud_cases


# ---- v1.1: balanced money flows --------------------------------------------------

def run(sim: Simulator, steps: int, start: datetime = TS) -> None:
    for i in range(steps):
        # Spread events over 30 days so paydays and normal days are both covered.
        sim.step(start + timedelta(hours=i * 720 / steps), random.Random(i))


def test_affordable_amount_is_the_largest_payable_amount() -> None:
    for tx_type in ("TRANSFER", "CASH_OUT", "PAYMENT"):
        for balance in (0, 99, 100, 101, 10_100, 523_456, 2_000_000):
            amount = affordable_amount(tx_type, balance)
            assert amount + fee_for(tx_type, amount) <= balance
            assert amount + 1 + fee_for(tx_type, amount + 1) > balance


def test_failure_rate_is_realistic() -> None:
    """The v1.0 bug: 16-31 % refusals. Target: a few percent, mostly deliberate over-spending."""
    sim, api = make_sim()
    run(sim, 6_000, start=datetime(2026, 11, 1, tzinfo=UTC))
    assert 0.01 <= sim.stats.failure_rate() <= 0.05, sim.stats.by_type_status
    assert total_money(api) == 0


def test_money_keeps_circulating() -> None:
    """Merchants withdraw their takings and salaries arrive: customers are not drained."""
    sim, api = make_sim()
    run(sim, 6_000, start=datetime(2026, 11, 1, tzinfo=UTC))
    merchants = sum(api.balances[m] for m in sim.pop.merchants)
    customers = sum(api.balances[c] for c in sim.pop.customers)
    assert sim.stats.merchant_cash_outs > 0
    assert sim.stats.salaries > 0
    assert merchants < customers, f"merchants={merchants} customers={customers}"


def test_onboarding_happens_the_day_before_the_window() -> None:
    _, api = make_sim()
    times = [t for t in api.occurred_at.values() if t is not None]
    assert times
    day_before = TS.replace(hour=0) - timedelta(days=1)
    assert all(day_before <= t < day_before + timedelta(days=1) for t in times)
    assert all(6 <= t.hour < 21 for t in times)


def test_a_second_run_on_the_same_database_gets_new_phone_numbers() -> None:
    """Bug found in phase 2a: `live` after `backfill` reused seed 42, hence the same phone
    numbers, and payment-core rightly refused the duplicates (422)."""
    api = FakePaymentApi()
    first = build_population(api, random.Random(42), n_customers=50, n_merchants=5, n_agents=3, start=TS)
    second = build_population(api, random.Random(42), n_customers=50, n_merchants=5, n_agents=3, start=None)
    assert set(first.customers).isdisjoint(second.customers)
    assert len(api.phones) == 2 * (50 + 5 + 3)
