"""`analytics pipeline`: load silver into DuckDB, run dbt (models + tests), publish if everything passed.

Exit code 0 = published, 1 = a dbt model or test failed (the previous warehouse stays online).
"""

from __future__ import annotations

import argparse
import sys
import time

from kaarangepay_analytics.config import Settings
from kaarangepay_analytics.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pipeline", help="load + dbt build + publish")
    args = parser.parse_args(argv)

    if args.command == "pipeline":
        started = time.monotonic()
        result = run_pipeline(Settings())
        print("\nloaded from the lakehouse:")
        for item in result.loaded:
            version = "absent, empty table" if item.version is None else f"Delta version {item.version}"
            print(f"  raw.{item.table:<16}{item.rows:>10,} rows   ({version})")
        state = "PUBLISHED" if result.published else "NOT PUBLISHED (dbt failed, previous warehouse kept)"
        print(f"\nwarehouse {state} in {time.monotonic() - started:.1f}s")
        return 0 if result.published else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
