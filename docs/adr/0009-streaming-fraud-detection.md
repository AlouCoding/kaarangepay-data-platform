# ADR 0009 — Real-time fraud detection with Spark Structured Streaming

- **Status:** Accepted
- **Date:** 2026-11-18

## Context
The traffic generator injects account takeovers (PaySim pattern): the victim's wallet is drained by
a TRANSFER to a **mule**, who withdraws almost all of it as cash at an agent 2–30 minutes later.
Ground-truth labels are written to `data/labels/fraud_labels.jsonl`, never seen by the payment API.
We want alerts within seconds, and a **measured** detection quality, not a claimed one.

## Decisions
| Topic | Decision | Why |
|---|---|---|
| Engine | Spark **Structured Streaming** reading Kafka directly | Same engine and same decoding code as silver; reading bronze would add up to 30 s of latency |
| Rule | **Pass-through**: incoming TRANSFER ≥ 5,000 XOF, then a CASH_OUT of 90–100 % of it by the receiver within 30 min | Velocity rules miss the mule (only 2 moves); the link between the 2 moves is the signal |
| Mechanism | **Stream-stream join** on the receiver's account, bounded in **event time** (`occurred_at`) | The time bound + watermark let Spark drop old state: memory stays bounded |
| Watermark | **45 minutes** | In backfill, a cash-out is submitted with an event time up to 30 min ahead; a shorter watermark would drop the next normal events as late |
| Sinks | Kafka topic `kaarangepay.fraud.alerts` (real time) + Delta table `gold/fraud_alerts` (analysis) | Consumers react on the topic; the evaluation reads the table |
| Fault tolerance | One **checkpoint** per sink on S3 (offsets + join state) | Restart resumes exactly where it stopped |
| Alert id | `alert_id` = cash-out transaction id | Deterministic: a replayed alert has the same key, consumers can deduplicate |
| Run modes | `lake fraud` (process what is available, stop) and `lake fraud --continuous` (micro-batch every 10 s) | Demo and tests on history; live mode for real time |

## Delivery guarantees
- Delta sink: **exactly once** (Delta records which micro-batch ids are committed).
- Kafka sink: **at least once** (Kafka has no idempotent write from Spark here): duplicates are possible
  after a crash, hence the deterministic `alert_id`.

## Evaluation
`lake fraud-eval` joins the alerts with the labels (only labels whose transaction exists in silver)
and reports **precision** (share of flagged transactions that are real fraud) and **recall** (share of
fraudulent transactions flagged), plus the share of fraud cases detected.

## Consequences
- ✅ The rule is a pure DataFrame function: unit-tested in batch **and** in streaming (file source + watermark).
- ⚠️ Honest customers who receive money and immediately withdraw nearly all of it (remittances!) match the
  rule: false positives are expected and measured, not hidden. Lowering them needs more context
  (account age, usual behaviour, mule network) — phase 5 (ML).
- ⚠️ The rule only alerts **after** the cash-out: the money is already gone. Blocking would need the
  decision inside payment-core, before the cash-out is accepted.
