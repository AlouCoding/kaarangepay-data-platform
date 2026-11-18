"""Customer behaviour: who pays whom, how much, and when fraud happens.

The transaction mix and naming follow the public PaySim dataset (CASH_IN,
CASH_OUT, PAYMENT, TRANSFER) so that the generated data can be compared with it.
Amounts and weights are illustrative assumptions in XOF, not operator data.
"""

from __future__ import annotations

import math
import random
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mmgen.client import TREASURY_ID, PaymentApi, TxResult
from mmgen.labels import LabelSink

# PaySim-like mix of customer-initiated transactions.
TRANSACTION_MIX: dict[str, float] = {
    "CASH_OUT": 0.35,
    "PAYMENT": 0.34,
    "CASH_IN": 0.22,
    "TRANSFER": 0.09,
}

# Log-normal amount distributions: (median in XOF, sigma).
AMOUNT_PROFILE: dict[str, tuple[float, float]] = {
    "CASH_IN": (15_000, 0.9),
    "CASH_OUT": (12_000, 0.9),
    "PAYMENT": (3_500, 1.0),
    "TRANSFER": (10_000, 1.1),
}
MIN_AMOUNT = 100
MAX_AMOUNT = 2_000_000
AGENT_TOPUP_AMOUNT = 5_000_000

FIRST_NAMES = ("Aminata", "Moussa", "Fatou", "Ibrahima", "Awa", "Mamadou", "Khady", "Ousmane",
               "Mariama", "Cheikh", "Ndeye", "Abdoulaye", "Coumba", "Babacar", "Astou", "Pape")
LAST_NAMES = ("Diop", "Ndiaye", "Fall", "Sow", "Ba", "Diallo", "Faye", "Sarr", "Gueye", "Mbaye",
              "Cisse", "Kane", "Thiam", "Seck", "Ndour", "Diouf")


def sample_amount(tx_type: str, rng: random.Random) -> int:
    """Log-normal amount, rounded to 25 XOF (smallest coin), clamped to sane bounds."""
    median, sigma = AMOUNT_PROFILE[tx_type]
    raw = rng.lognormvariate(math.log(median), sigma)
    rounded = round(raw / 25.0) * 25
    return max(MIN_AMOUNT, min(MAX_AMOUNT, rounded))


@dataclass
class Population:
    agents: list[str]
    merchants: list[str]
    customers: list[str]
    customer_weights: list[float]   # heavy users transact much more than others
    merchant_weights: list[float]   # a few merchants get most payments
    home_agent: dict[str, str]      # each customer has a usual agent
    mules: set[str]                 # accounts used by fraudsters to cash out


@dataclass
class Stats:
    by_type_status: Counter[str] = field(default_factory=Counter)
    replays: int = 0
    fraud_cases: int = 0
    agent_topups: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, tx_type: str, result: TxResult) -> None:
        with self._lock:
            self.by_type_status[f"{tx_type}:{result.status or 'REJECTED'}"] += 1
            if result.replayed:
                self.replays += 1

    def bump(self, attr: str) -> None:
        with self._lock:
            setattr(self, attr, getattr(self, attr) + 1)

    @property
    def total(self) -> int:
        return sum(self.by_type_status.values())


class PhoneBook:
    """Unique fictional Senegalese-format mobile numbers (+221 7X XXX XX XX)."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._used: set[str] = set()

    def new(self) -> str:
        while True:
            phone = f"+2217{self._rng.choice('05678')}{self._rng.randint(0, 9_999_999):07d}"
            if phone not in self._used:
                self._used.add(phone)
                return phone


def build_population(
    api: PaymentApi,
    rng: random.Random,
    n_customers: int,
    n_merchants: int,
    n_agents: int,
    start: datetime | None,
) -> Population:
    """Opens accounts, funds agents, and gives each customer an initial balance."""
    phones = PhoneBook(rng)

    def name() -> str:
        return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"

    agents = [api.open_account(phones.new(), f"Agent {name()}", "AGENT") for _ in range(n_agents)]
    merchants = [api.open_account(phones.new(), f"Boutique {name()}", "MERCHANT") for _ in range(n_merchants)]
    customers = [api.open_account(phones.new(), name(), "CUSTOMER") for _ in range(n_customers)]

    for agent in agents:
        api.submit(_key(), "FLOAT_TOPUP", TREASURY_ID, agent, AGENT_TOPUP_AMOUNT, start)

    home_agent = {c: rng.choice(agents) for c in customers}
    for customer in customers:
        initial = sample_amount("CASH_IN", rng) * 2
        api.submit(_key(), "CASH_IN", home_agent[customer], customer, initial, start)

    n_mules = max(1, n_customers // 100)
    return Population(
        agents=agents,
        merchants=merchants,
        customers=customers,
        customer_weights=[rng.paretovariate(1.5) for _ in customers],
        merchant_weights=[1.0 / (rank + 1) for rank in range(len(merchants))],  # Zipf-like
        home_agent=home_agent,
        mules=set(rng.sample(customers, n_mules)),
    )


def _key() -> str:
    return str(uuid.uuid4())


class Simulator:
    """Turns one event time into one (or a few) API calls."""

    def __init__(
        self,
        api: PaymentApi,
        population: Population,
        labels: LabelSink,
        fraud_rate: float = 0.002,
        duplicate_rate: float = 0.01,
    ) -> None:
        self.api = api
        self.pop = population
        self.labels = labels
        self.fraud_rate = fraud_rate
        self.duplicate_rate = duplicate_rate
        self.stats = Stats()
        self._honest_customers = [c for c in population.customers if c not in population.mules]

    def step(self, ts: datetime | None, rng: random.Random) -> None:
        if rng.random() < self.fraud_rate:
            self.account_takeover(ts, rng)
            return
        tx_type = rng.choices(list(TRANSACTION_MIX), weights=list(TRANSACTION_MIX.values()))[0]
        customer = rng.choices(self.pop.customers, weights=self.pop.customer_weights)[0]
        amount = sample_amount(tx_type, rng)

        # Outcomes are recorded in self.stats by _submit.
        if tx_type == "CASH_IN":
            self._submit_with_float(tx_type, self._agent_for(customer, rng), customer, amount, ts, rng)
        elif tx_type == "CASH_OUT":
            self._submit(tx_type, customer, self._agent_for(customer, rng), amount, ts, rng)
        elif tx_type == "PAYMENT":
            merchant = rng.choices(self.pop.merchants, weights=self.pop.merchant_weights)[0]
            self._submit(tx_type, customer, merchant, amount, ts, rng)
        else:  # TRANSFER
            recipient = rng.choice(self.pop.customers)
            if recipient != customer:
                self._submit(tx_type, customer, recipient, amount, ts, rng)

    def account_takeover(self, ts: datetime | None, rng: random.Random) -> None:
        """PaySim's fraud pattern: drain a victim with a TRANSFER to a mule,
        then the mule withdraws the cash at an agent a few minutes later."""
        victim = rng.choice(self._honest_customers)
        mule = rng.choice(sorted(self.pop.mules))
        balance = self.api.balance(victim)
        if balance < 5_000:
            return
        drained = balance * 100 // 101  # leaves room for the 1 % transfer fee
        transfer = self._submit("TRANSFER", victim, mule, drained, ts, rng)
        if not transfer.completed or transfer.transaction_id is None:
            return
        self.stats.bump("fraud_cases")
        self._label(transfer, "drain_transfer", ts)

        cash_out_ts = ts + timedelta(minutes=rng.uniform(2, 30)) if ts is not None else None
        cash_out = self._submit("CASH_OUT", mule, rng.choice(self.pop.agents), drained * 200 // 201,
                                cash_out_ts, rng)
        if cash_out.completed and cash_out.transaction_id is not None:
            self._label(cash_out, "mule_cash_out", cash_out_ts)

    # ---- internals ------------------------------------------------------------

    def _agent_for(self, customer: str, rng: random.Random) -> str:
        return self.pop.home_agent[customer] if rng.random() < 0.8 else rng.choice(self.pop.agents)

    def _submit(self, tx_type: str, source: str, destination: str, amount: int,
                ts: datetime | None, rng: random.Random) -> TxResult:
        key = _key()
        result = self.api.submit(key, tx_type, source, destination, amount, ts)
        self.stats.record(tx_type, result)
        if rng.random() < self.duplicate_rate:
            # Simulates a client that lost the response and retries: must be a replay.
            self.stats.record(tx_type, self.api.submit(key, tx_type, source, destination, amount, ts))
        return result

    def _submit_with_float(self, tx_type: str, agent: str, customer: str, amount: int,
                           ts: datetime | None, rng: random.Random) -> TxResult:
        """An agent short of e-money goes to the bank (FLOAT_TOPUP), then serves the customer."""
        result = self._submit(tx_type, agent, customer, amount, ts, rng)
        if result.failure_reason == "INSUFFICIENT_FUNDS":
            self.api.submit(_key(), "FLOAT_TOPUP", TREASURY_ID, agent, AGENT_TOPUP_AMOUNT, ts)
            self.stats.bump("agent_topups")
            result = self._submit(tx_type, agent, customer, amount, ts, rng)
        return result

    def _label(self, result: TxResult, role: str, ts: datetime | None) -> None:
        assert result.transaction_id is not None
        self.labels.add(result.transaction_id, "account_takeover", role, ts or datetime.now().astimezone())
