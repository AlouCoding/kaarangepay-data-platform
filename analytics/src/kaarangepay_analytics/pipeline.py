"""The analytics pipeline:  load (silver Delta -> DuckDB raw)  ->  dbt build (models + tests)  ->  publish.

The pipeline never writes into the file the dashboard is reading. It builds a NEW DuckDB file next to
it, and only if every dbt model and test passed, swaps it in with an atomic rename. So:
  * the dashboard never sees a half-built warehouse;
  * a failed test keeps yesterday's (correct) numbers online instead of publishing wrong ones.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kaarangepay_analytics.config import Settings
from kaarangepay_analytics.load import Loaded, load_raw

DBT_DIR = Path(os.environ.get("DBT_PROJECT_DIR", Path(__file__).resolve().parents[2] / "dbt"))


@dataclass(frozen=True)
class PipelineResult:
    loaded: list[Loaded]
    dbt_ok: bool
    published: bool


def run_dbt(duckdb_path: Path, args: list[str]) -> bool:
    """Runs dbt in a SEPARATE process.

    Found by a test: run in-process, dbt-duckdb keeps its connection open, so recent writes still sit in
    the `.wal` file next to the database. Renaming the database then left the marts behind in that WAL.
    A separate process closes DuckDB on exit, which checkpoints everything into the database file.
    """
    dbt = shutil.which("dbt") or "dbt"
    env = {**os.environ, "DUCKDB_PATH": str(duckdb_path)}
    command = [dbt, *args, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    return subprocess.run(command, env=env, check=False).returncode == 0


def run_pipeline(settings: Settings) -> PipelineResult:
    final = settings.warehouse
    building = final.with_name(final.stem + ".building.duckdb")
    building.unlink(missing_ok=True)
    Path(f"{building}.wal").unlink(missing_ok=True)

    loaded = load_raw(settings, building)
    ok = run_dbt(building, ["build"])
    if ok:
        if Path(f"{building}.wal").exists():   # never publish a database whose last writes are elsewhere
            raise RuntimeError(f"{building}.wal still exists after dbt: refusing to publish")
        os.replace(building, final)   # atomic on the same filesystem
    return PipelineResult(loaded, ok, published=ok)
