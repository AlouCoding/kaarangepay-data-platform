# ADR 0010 — Analytics layer: dbt on DuckDB, published atomically, read by a Streamlit app

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
Silver (Delta, ADR 0008) and gold fraud alerts (ADR 0009) exist, but nobody outside engineering can use
them. Two end users matter most: **management** (daily KPIs) and the **fraud analyst** (live alerts to
review). The laptop already runs ~10 containers on 7.6 GB of RAM.

## Decisions
| Topic | Decision | Why |
|---|---|---|
| Transformation | **dbt** (models + tests + docs) | Industry standard for analytics engineering; tests are part of the build |
| Engine | **DuckDB** (`dbt-duckdb`), one file | In-process, no server, fast on this volume; no extra RAM-hungry warehouse |
| Extract | **delta-rs** reads the silver/gold Delta tables (via their transaction log) into `raw.*` | Reading raw Parquet would mix old and new files after a silver rebuild |
| Model | Star schema: `fct_transactions`, `dim_account`, `dim_date` + `agg_daily_kpis`, `agg_by_type`, `agg_activity_by_hour`, `fct_fraud_alerts` | Facts at event-time grain; aggregates the app reads directly |
| Quality | dbt generic tests (unique, not_null, accepted_values, relationships) + 4 singular tests (ledger balanced, balances sum to 0, failed tx earn nothing, daily = fact) | The ledger invariants are now checked in PostgreSQL, Spark **and** the warehouse |
| Publication | Build into a **new** DuckDB file, swap it in with an atomic rename **only if `dbt build` passed** | The app never sees a half-built warehouse; a failing test keeps the last good numbers online |
| dbt process | dbt runs in a **separate process** | In-process, DuckDB kept recent writes in its `.wal`; renaming the file left them behind (found by a test) |
| App | **Streamlit**, 2 pages: *Vue métier* (warehouse) and *Console fraude* (gold Delta read live every 10 s) | One light container, Python only, interactive enough for a demo |
| Analyst decisions | SQLite file next to the warehouse, never rebuilt | Human labels must survive every rebuild; they feed phase 5 (ML) |
| Orchestration | `analytics pipeline` command; **Airflow postponed** | Same steps, one command; an Airflow DAG can call it later without code changes |

## Consequences
- ✅ One command rebuilds and republishes everything, or publishes nothing.
- ✅ All of it is tested without Docker: real Delta tables, real dbt build, Streamlit `AppTest`.
- ⚠️ DuckDB is single-writer: fine for one pipeline + one read-only app; a shared multi-user warehouse would need
  PostgreSQL, Snowflake or BigQuery (dbt models would move with few changes).
- ⚠️ Times are shown in UTC, which is Dakar time (UTC+0, no daylight saving): correct here, not in general.
