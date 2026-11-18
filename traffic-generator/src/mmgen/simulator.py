"""Customer behaviour: who pays whom, how much, and when fraud happens.

The transaction mix and naming follow the public PaySim dataset (CASH_IN,
CASH_OUT, PAYMENT, TRANSFER) so that the generated data can be compared with it.
Amounts and weights are illustrative assumptions in XOF, not operator data.

v1.1 — money flows are balanced (see docs/JOURNAL-FR.md, session 1, issue 6):
  * customers know their balance and spend within it, except for a small,
    deliberate share of over-spending attempts (OVERSPEND_RATE);
  * a customer with an empty wallet goes to an agent (CASH_IN) instead of failing;
  * salaries arrive during the payday period;
  * merchants regularly withdraw their takings at an agent, so money circulates.
"""

from __future__ import annotations

import math
import random
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mmgen.client import TREASURY_ID, PaymentApi, PhoneAlreadyUsedError, TxResult
from mmgen.labels import LabelSink
from mmgen.patterns import is_payday_period

# PaySim-like mix of customer-initiated transactions.
TRANSACTION_MIX: dict[str, float] = {
    "PAYMENT": 0.38,
    "CASH_OUT": 0.30,
    "CASH_IN": 0.24,
    "TRANSFER": 0.08,
}

# Log-normal amount distributions: (median in XOF, sigma).
AMOUNT_PROFILE: dict[str, tuple[float, float]] = {
    "CASH_IN": (15_000, 0.9),
    "CASH_OUT": (12_000, 0.9),
    "PAYMENT": (3_500, 1.0),
    "TRANSFER": (10_000, 1.1),
    "SALARY": (80_000, 0.5),
}
MIN_AMOUNT = 100
MAX_AMOUNT = 2_000_000
AGENT_TOPUP_AMOUNT = 5_000_000

# Behaviour knobs (illustrative assumptions).
OVERSPEND_RATE = 0.03          # share of outgoing payments attempted above the balance
SALARY_RATE = 0.12             # extra salary deposits per event during the payday period
MERCHANT_CASH_OUT_RATE = 0.03  # merchants withdrawing their takings, per event
MERCHANT_CASH_OUT_MIN_BALANCE = 20_000
MAX_PHONE_ATTEMPTS = 1_000

# Mirror of payment-core's fee schedule (application.yml): needed to estimate balances.
FEE_BPS: dict[str, int] = {"TRANSFER": 100, "CASH_OUT": 50}
MAX_FEE = 5_000

FIRST_NAMES = ("Aminata", "Moussa", "Fatou", "Ibrahima", "Awa", "Mamadou", "Khady", "Ousmane",
               "Mariama", "Cheikh", "Ndeye", "Abdoulaye", "Coumba", "Babacar", "Astou", "Pape")
LAST_NAMES = ("Diop", "Ndiaye", "Fall", "Sow", "Ba", "Diallo", "Faye", "Sarr", "Gueye", "Mbaye",
              "Cisse", "Kane", "Thiam", "Seck", "Ndour", "Diouf")

OUTGOING_TYPES = ("PAYMENT", "CASH_OUT", "TRANSFER")


def fee_for(tx_type: str, amount: int) -> int:
    """Same rule as payment-core's FeePolicy: floor(amount * bps / 10 000), capped."""
    return min(amount * FEE_BPS.get(tx_type, 0) // 10_000, MAX_FEE)


def affordable_amount(tx_type: str, balance: int) -> int:
    """Largest amount whose amount + fee fits in ``balance`` (binary search: amount + fee is monotonic)."""
    low, high = 0, max(balance, 0)
    while low < high:
        mid = (low + high + 1) // 2
        if mid + fee_for(tx_type, mid) <= balance:
            low = mid
        else:
            high = mid - 1
    return low


def sample_amount(tx_type: str, rng: random.Random) -> int:
    """Log-normal amount, rounded to 25 XOF (smallest coin), clamped to sane bounds."""
    median, sigma = AMOUNT_PROFILE[tx_type]
    raw = rng.lognormvariate(math.log(median), sigma)
    rounded = round(raw / 25.0) * 25
    return max(MIN_AMOUNT, min(MAX_AMOUNT, rounded))


class BalanceBook:
    """The generator's own view of wallet balances, updated from API results.

    A real customer sees their balance in the app before paying. Under concurrency
    this view can lag slightly behind the server — which only adds a few
    realistic refusals. The server's ledger remains the source of truth.
    """

    def __init__(self) -> None:
        self._balances: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, account: str) -> int:
        with self._lock:
            return self._balances.get(account, 0)

    def apply(self, tx_type: str, source: str, destination: str, amount: int, result: TxResult) -> None:
        if not result.completed or result.replayed:
            return
        with self._lock:
            if source != TREASURY_ID:
                self._balances[source] = self._balances.get(source, 0) - amount - fee_for(tx_type, amount)
            self._balances[destination] = self._balances.get(destination, 0) + amount


@dataclass
class Population:
    agents: list[str]
    merchants: list[str]
    customers: list[str]
    customer_weights: list[float]   # heavy users transact much more than others
    merchant_weights: list[float]   # a few merchants get most payments
    home_agent: dict[str, str]      # each customer has a usual agent
    mules: set[str]                 # accounts used by fraudsters to cash out
    book: BalanceBook = field(default_factory=BalanceBook)


@dataclass
class Stats:
    by_type_status: Counter[str] = field(default_factory=Counter)
    replays: int = 0
    fraud_cases: int = 0
    agent_topups: int = 0
    salaries: int = 0
    merchant_cash_outs: int = 0
    overspend_attempts: int = 0
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

    def failure_rate(self) -> float:
        """Share of FAILED among first attempts (replays excluded)."""
        failed = sum(n for k, n in self.by_type_status.items() if k.endswith(":FAILED"))
        attempts = self.total - self.replays
        return failed / attempts if attempts else 0.0


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


def _key() -> str:
    return str(uuid.uuid4())


def build_population(
    api: PaymentApi,
    rng: random.Random,
    n_customers: int,
    n_merchants: int,
    n_agents: int,
    start: datetime | None,
) -> Population:
    """Opens accounts, funds agents and gives each customer an initial balance.

    Onboarding is dated on the **day before** ``start`` (agents at 06:00-07:00,
    customers between 08:00 and 21:00), so the simulated window itself contains
    only normal activity — no artificial spike at midnight on day 1.
    """
    phones = PhoneBook(rng)
    book = BalanceBook()

    def name() -> str:
        return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"

    def onboarding_time(first_hour: float, last_hour: float) -> datetime | None:
        if start is None:
            return None
        previous_midnight = start.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        return previous_midnight + timedelta(hours=rng.uniform(first_hour, last_hour))

    def open_account(owner: str, account_type: str) -> str:
        """The database may already hold accounts from an earlier run (same seed, same numbers):
        a taken number is simply replaced by a new one, like an operator would do."""
        for _ in range(MAX_PHONE_ATTEMPTS):
            try:
                return api.open_account(phones.new(), owner, account_type)
            except PhoneAlreadyUsedError:
                continue
        raise RuntimeError(f"No free phone number after {MAX_PHONE_ATTEMPTS} attempts")

    def submit(tx_type: str, source: str, destination: str, amount: int, ts: datetime | None) -> None:
        result = api.submit(_key(), tx_type, source, destination, amount, ts)
        book.apply(tx_type, source, destination, amount, result)

    agents = [open_account(f"Agent {name()}", "AGENT") for _ in range(n_agents)]
    merchants = [open_account(f"Boutique {name()}", "MERCHANT") for _ in range(n_merchants)]
    customers = [open_account(name(), "CUSTOMER") for _ in range(n_customers)]

    for agent in agents:
        submit("FLOAT_TOPUP", TREASURY_ID, agent, AGENT_TOPUP_AMOUNT, onboarding_time(6, 7))

    home_agent = {c: rng.choice(agents) for c in customers}
    for customer in customers:
        submit("CASH_IN", home_agent[customer], customer, sample_amount("CASH_IN", rng) * 2,
               onboarding_time(8, 21))

    n_mules = max(1, n_customers // 100)
    return Population(
        agents=agents,
        merchants=merchants,
        customers=customers,
        customer_weights=[rng.paretovariate(1.5) for _ in customers],
        merchant_weights=[1.0 / (rank + 1) for rank in range(len(merchants))],  # Zipf-like
        home_agent=home_agent,
        mules=set(rng.sample(customers, n_mules)),
        book=book,
    )


class Simulator:
    """Turns one event time into one (or a few) API calls."""

    def __init__(
        self,
        api: PaymentApi,
        population: Population,
        labels: LabelSink,
        fraud_rate: float = 0.002,
        duplicate_rate: float = 0.01,
        overspend_rate: float = OVERSPEND_RATE,
    ) -> None:
        self.api = api
        self.pop = population
        self.book = population.book
        self.labels = labels
        self.fraud_rate = fraud_rate
        self.duplicate_rate = duplicate_rate
        self.overspend_rate = overspend_rate
        self.stats = Stats()
        self._honest_customers = [c for c in population.customers if c not in population.mules]

    def step(self, ts: datetime | None, rng: random.Random) -> None:
        roll = rng.random()
        if roll < self.fraud_rate:
            self.account_takeover(ts, rng)
            return
        if roll < self.fraud_rate + MERCHANT_CASH_OUT_RATE:
            self.merchant_cash_out(ts, rng)
            return
        day = (ts or datetime.now()).date()
        if is_payday_period(day) and rng.random() < SALARY_RATE:
            self.salary(ts, rng)
            return

        tx_type = rng.choices(list(TRANSACTION_MIX), weights=list(TRANSACTION_MIX.values()))[0]
        customer = rng.choices(self.pop.customers, weights=self.pop.customer_weights)[0]

        if tx_type == "CASH_IN":
            self._cash_in(customer, sample_amount("CASH_IN", rng), ts, rng)
            return

        if tx_type == "PAYMENT":
            destination = rng.choices(self.pop.merchants, weights=self.pop.merchant_weights)[0]
        elif tx_type == "CASH_OUT":
            destination = self._agent_for(customer, rng)
        else:  # TRANSFER
            destination = rng.choice(self.pop.customers)
            if destination == customer:
                return

        amount = self._choose_spend(tx_type, customer, rng)
        if amount is None:
            # Empty wallet: a real customer goes to an agent first.
            self._cash_in(customer, sample_amount("CASH_IN", rng), ts, rng)
            return
        self._submit(tx_type, customer, destination, amount, ts, rng)

    # ---- scenarios -------------------------------------------------------------

    def salary(self, ts: datetime | None, rng: random.Random) -> None:
        """Payday: a salary is cashed in on the customer's wallet."""
        customer = rng.choices(self.pop.customers, weights=self.pop.customer_weights)[0]
        self.stats.bump("salaries")
        self._cash_in(customer, sample_amount("SALARY", rng), ts, rng)

    def merchant_cash_out(self, ts: datetime | None, rng: random.Random) -> None:
        """A merchant withdraws most of their takings at an agent: money goes back into circulation."""
        balances = [self.book.get(m) for m in self.pop.merchants]
        if max(balances, default=0) < MERCHANT_CASH_OUT_MIN_BALANCE:
            return
        merchant = rng.choices(self.pop.merchants, weights=[max(b, 0) for b in balances])[0]
        available = affordable_amount("CASH_OUT", self.book.get(merchant))
        amount = int(available * rng.uniform(0.6, 0.9)) // 25 * 25
        if amount < MIN_AMOUNT:
            return
        self.stats.bump("merchant_cash_outs")
        self._submit("CASH_OUT", merchant, rng.choice(self.pop.agents), amount, ts, rng)

    def account_takeover(self, ts: datetime | None, rng: random.Random) -> None:
        """PaySim's fraud pattern: drain a victim with a TRANSFER to a mule,
        then the mule withdraws the cash at an agent a few minutes later."""
        victim = rng.choice(self._honest_customers)
        mule = rng.choice(sorted(self.pop.mules))
        balance = self.api.balance(victim)
        if balance < 5_000:
            return
        drained = affordable_amount("TRANSFER", balance)
        transfer = self._submit("TRANSFER", victim, mule, drained, ts, rng)
        if not transfer.completed or transfer.transaction_id is None:
            return
        self.stats.bump("fraud_cases")
        self._label(transfer, "drain_transfer", ts)

        cash_out_ts = ts + timedelta(minutes=rng.uniform(2, 30)) if ts is not None else None
        cash_out = self._submit("CASH_OUT", mule, rng.choice(self.pop.agents),
                                affordable_amount("CASH_OUT", drained), cash_out_ts, rng)
        if cash_out.completed and cash_out.transaction_id is not None:
            self._label(cash_out, "mule_cash_out", cash_out_ts)

    # ---- internals ------------------------------------------------------------

    def _choose_spend(self, tx_type: str, customer: str, rng: random.Random) -> int | None:
        """How much the customer tries to spend, or None if the wallet is (nearly) empty.

        Most of the time the amount fits the balance. A small share of attempts
        deliberately exceeds it: those refusals are realistic and useful signals.
        """
        balance = self.book.get(customer)
        wanted = sample_amount(tx_type, rng)
        if rng.random() < self.overspend_rate:
            self.stats.bump("overspend_attempts")
            return max(wanted, balance + MIN_AMOUNT)
        affordable = affordable_amount(tx_type, balance)
        if affordable < MIN_AMOUNT:
            return None
        return min(wanted, affordable // 25 * 25) if affordable >= 25 else None

    def _cash_in(self, customer: str, amount: int, ts: datetime | None, rng: random.Random) -> TxResult:
        return self._submit_with_float("CASH_IN", self._agent_for(customer, rng), customer, amount, ts, rng)

    def _agent_for(self, customer: str, rng: random.Random) -> str:
        return self.pop.home_agent[customer] if rng.random() < 0.8 else rng.choice(self.pop.agents)

    def _submit(self, tx_type: str, source: str, destination: str, amount: int,
                ts: datetime | None, rng: random.Random) -> TxResult:
        key = _key()
        result = self.api.submit(key, tx_type, source, destination, amount, ts)
        self.stats.record(tx_type, result)
        self.book.apply(tx_type, source, destination, amount, result)
        if rng.random() < self.duplicate_rate:
            # Simulates a client that lost the response and retries: must be a replay.
            self.stats.record(tx_type, self.api.submit(key, tx_type, source, destination, amount, ts))
        return result

    def _submit_with_float(self, tx_type: str, agent: str, customer: str, amount: int,
                           ts: datetime | None, rng: random.Random) -> TxResult:
        """An agent short of e-money goes to the bank (FLOAT_TOPUP), then serves the customer."""
        if self.book.get(agent) < amount:
            self._topup(agent, ts)
        result = self._submit(tx_type, agent, customer, amount, ts, rng)
        if result.failure_reason == "INSUFFICIENT_FUNDS":
            self._topup(agent, ts)
            result = self._submit(tx_type, agent, customer, amount, ts, rng)
        return result

    def _topup(self, agent: str, ts: datetime | None) -> None:
        result = self.api.submit(_key(), "FLOAT_TOPUP", TREASURY_ID, agent, AGENT_TOPUP_AMOUNT, ts)
        self.book.apply("FLOAT_TOPUP", TREASURY_ID, agent, AGENT_TOPUP_AMOUNT, result)
        self.stats.bump("agent_topups")

    def _label(self, result: TxResult, role: str, ts: datetime | None) -> None:
        assert result.transaction_id is not None
        self.labels.add(result.transaction_id, "account_takeover", role, ts or datetime.now().astimezone())
