"""Command line entry point.

Examples::

    # 30 days of history from 1 Nov 2026, as fast as the API allows (needs ALLOW_CLIENT_CLOCK=true)
    mmgen backfill --start 2026-11-01 --days 30 --rate 300

    # Continuous real-time traffic, following today's clock
    mmgen live --rate 600
"""

from __future__ import annotations

import argparse
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mmgen.client import HttpPaymentApi
from mmgen.labels import LabelSink
from mmgen.patterns import TrafficCalendar
from mmgen.simulator import Simulator, build_population
from mmgen.timeline import event_times

log = logging.getLogger("mmgen")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mmgen", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--customers", type=int, default=500)
    parser.add_argument("--merchants", type=int, default=40)
    parser.add_argument("--agents", type=int, default=15)
    parser.add_argument("--rate", type=float, default=300.0,
                        help="transactions per hour at intensity 1.0 (peak hour, normal day)")
    parser.add_argument("--fraud-rate", type=float, default=0.002)
    parser.add_argument("--duplicate-rate", type=float, default=0.01)
    parser.add_argument("--labels", type=Path, default=Path("data/labels/fraud_labels.jsonl"))
    parser.add_argument("--seed", type=int, default=42)
    sub = parser.add_subparsers(dest="mode", required=True)

    backfill = sub.add_parser("backfill", help="generate history with simulated event times")
    backfill.add_argument("--start", type=datetime.fromisoformat, required=True,
                          help="ISO date, e.g. 2026-11-01")
    backfill.add_argument("--days", type=int, default=30)
    backfill.add_argument("--workers", type=int, default=8)

    live = sub.add_parser("live", help="real-time traffic following the current clock")
    live.add_argument("--duration-min", type=float, default=0, help="0 = run forever")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is unreadable at 300 tx/s
    args = parse_args(argv)
    rng = random.Random(args.seed)
    api = HttpPaymentApi(args.base_url)
    labels = LabelSink(args.labels)

    try:
        if args.mode == "backfill":
            start = args.start if args.start.tzinfo else args.start.replace(tzinfo=UTC)
            run_backfill(api, labels, rng, args, start)
        else:
            run_live(api, labels, rng, args)
    finally:
        api.close()


def run_backfill(api: HttpPaymentApi, labels: LabelSink, rng: random.Random,
                 args: argparse.Namespace, start: datetime) -> None:
    end = start + timedelta(days=args.days)
    calendar = TrafficCalendar.for_years(*range(start.year, end.year + 1))
    log.info("Opening accounts: %d customers, %d merchants, %d agents",
             args.customers, args.merchants, args.agents)
    population = build_population(api, rng, args.customers, args.merchants, args.agents, start)
    sim = Simulator(api, population, labels, args.fraud_rate, args.duplicate_rate)

    times = list(event_times(calendar, start, end, args.rate, rng))
    log.info("Backfilling %d events from %s to %s with %d workers", len(times), start, end, args.workers)
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        # One seeded RNG per event: the scenario is reproducible regardless of thread scheduling.
        futures = [pool.submit(sim.step, ts, random.Random(args.seed * 1_000_003 + i))
                   for i, ts in enumerate(times)]
        for done, future in enumerate(futures, start=1):
            future.result()
            if done % 1000 == 0:
                log.info("%d/%d events", done, len(times))
    report(sim, time.monotonic() - began)


def run_live(api: HttpPaymentApi, labels: LabelSink, rng: random.Random, args: argparse.Namespace) -> None:
    now = datetime.now(UTC)
    calendar = TrafficCalendar.for_years(now.year, now.year + 1)
    population = build_population(api, rng, args.customers, args.merchants, args.agents, None)
    sim = Simulator(api, population, labels, args.fraud_rate, args.duplicate_rate)
    deadline = time.monotonic() + args.duration_min * 60 if args.duration_min > 0 else float("inf")
    began = time.monotonic()
    log.info("Live traffic started (Ctrl+C to stop)")
    try:
        while time.monotonic() < deadline:
            rate_per_second = args.rate * calendar.intensity(datetime.now(UTC)) / 3600.0
            time.sleep(rng.expovariate(max(rate_per_second, 1e-6)))
            sim.step(None, rng)
    except KeyboardInterrupt:
        pass
    report(sim, time.monotonic() - began)


def report(sim: Simulator, elapsed_s: float) -> None:
    stats = sim.stats
    log.info("Done in %.1fs — %d API calls (%.0f/s)", elapsed_s, stats.total,
             stats.total / elapsed_s if elapsed_s else 0)
    for key, count in sorted(stats.by_type_status.items()):
        log.info("  %-28s %8d", key, count)
    log.info("  replays=%d fraud_cases=%d agent_topups=%d",
             stats.replays, stats.fraud_cases, stats.agent_topups)


if __name__ == "__main__":
    main()
