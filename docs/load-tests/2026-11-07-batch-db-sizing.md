# Load Test: Temporal DB Sizing — Controllable Batch

**Date:** 2026-11-07
**Process under test:** `example_batch_controllable`
**Goal:** Measure how much Postgres storage one transaction consumes, so we can
size the database for a **60-day retention** window.

**Visibility store:** this run uses **Postgres** visibility
(`docker-compose-postgres.yml`, no Elasticsearch), so all three growth stores —
history, mutable state, and the UI/search `executions_visibility` table — live in
Postgres and are measured together. (An earlier run on the Elasticsearch-backed
stack gave the same history/state numbers; only the visibility store differs.)

---

## TL;DR

| Metric | Value |
|---|---:|
| Transactions run | 10,000 items (100,000 activity executions, 101 workflow executions) |
| Outcome | processed 8,970 / failed 1,030 |
| **Retained storage per transaction** | **~9.3 KiB/item** (history_node + executions + visibility) |
| Prediction, **batched** model (100 items/wf) | **~2.3 GiB** for 260k items |
| Prediction, **1-workflow-per-transaction** | **~14.6 GiB** for 260k — visibility dominates |

> **The single biggest driver is how many Temporal *workflow executions* you
> create.** History and visibility both scale per workflow execution, and the
> Postgres visibility table is ~98% indexes, so one workflow per transaction is
> far more expensive than batching many transactions into one workflow.

---

## Environment

| Component | Value |
|---|---|
| Temporal server | `temporalio/server:1.31.0` (Docker Compose, `localhost:7233`) |
| Persistence | `postgres:16` (`temporal-postgresql`) |
| Databases | `temporal` (history/state) + `temporal_visibility` (UI/search) |
| Visibility store | **Postgres** (`ENABLE_ES` off; `docker-compose-postgres.yml`) |
| Namespace | `default` |
| Python SDK | `temporalio` 1.35.0 |

---

## Workload definition

`example_batch_controllable` runs a **10-step pipeline per item**:

- Each item flows through activities `step_01` … `step_10` **in sequence**.
- Success/failure is **deterministic**, driven by config (never by workflow input)
  so the test is reproducible. For `key = item_id * 10 + step_no`:
  - **Transient** failure (retryable `RuntimeError`) when `key % BATCH_FAIL_EVERY == 0`
    on the first attempt → retry succeeds (adds extra history events).
  - **Permanent** failure (non-retryable `ValueError`) when `key % BATCH_INVALID_EVERY == 0`
    → the item's pipeline stops there and the item is counted failed.
- Per-step latency from config `BATCH_STEP_SLEEP_MS` (set to `0` — latency does
  not affect stored size, only wall-clock).

Config used (defaults): `BATCH_FAIL_EVERY=17`, `BATCH_INVALID_EVERY=97`, `BATCH_STEP_SLEEP_MS=0`.

**Grouping:** `--total 10000 --batch-size 100 --concurrency 20 --batches-per-run 100`
→ 10,000 items become **101 workflow executions** (1 parent + 100 child batches).
This grouping is the key variable for visibility cost (see below).

---

## Method

1. `VACUUM ANALYZE` both databases, record baseline (`pg_total_relation_size`, `pg_database_size`).
2. Start 6 worker processes (`BATCH_STEP_SLEEP_MS=0`, `MAX_CONCURRENT_ACTIVITIES=10` each).
3. Start one parent workflow (parameters above); wait for completion.
4. `VACUUM ANALYZE` both databases, record sizes again.
5. Diff per table + totals; divide by 10,000 items (and by 101 executions for visibility).

---

## Results

### `temporal` database (history + state)

| Table | Before | After | Diff | B/item |
|---|---:|---:|---:|---:|
| `history_node` (events) | 0.06 MiB | 81.15 MiB | **+81.09 MiB** | 8,502 |
| `executions` (mutable state) | 0.06 MiB | 4.61 MiB | **+4.55 MiB** | 477 |
| **DB total** | 9.49 MiB | 126.65 MiB | **+117.16 MiB** | — |

`history_node` grew by ~137k rows (event history is chunked across nodes). The DB
total exceeds the two tables because of transient task tables (`timer_tasks`,
`tasks`, `transfer_tasks`, `activity_info_maps`) that inflate during the run and
are then emptied — a fixed high-water overhead (~20 MiB) that scales with
concurrency, **not** with retained transaction count.

### `temporal_visibility` database (UI / search)

| Table | Before | After | Diff | B/item | B/execution |
|---|---:|---:|---:|---:|---:|
| `executions_visibility` | 1.64 MiB | 6.59 MiB | **+4.95 MiB** | 519 | 51,342 |
| **DB total** | 10.01 MiB | 15.11 MiB | **+5.09 MiB** | — | — |

**`executions_visibility` is ~98% indexes:** after the run its 6.59 MiB splits into
**120 KiB of actual row data (heap)** and **6.47 MiB across 74 indexes**. Temporal
pre-creates an index for every reserved and custom search attribute, so this table
is dominated by index storage and scales with **workflow execution count**, not item count.

---

## Per-transaction cost (batched model, 100 items/execution)

```
retained per item = history_node + executions + executions_visibility
                  = 8,502 B + 477 B + 519 B
                  = 9,498 B  (≈ 9.28 KiB/item)
```

Visibility is only ~519 B/item **because 100 items share one workflow execution**.
Per execution it is ~50 KiB — see the warning below.

---

## Prediction: 260,000 transactions

The answer depends entirely on **how many workflow executions** 260k transactions become:

| Model | history+state | visibility | **Total** |
|---|---:|---:|---:|
| **Batched** (100 items/wf → 2,600 executions) | 2.17 GiB | 0.13 GiB | **~2.3 GiB** |
| **1 workflow per transaction** (260k executions) | 2.17 GiB | **12.4 GiB** | **~14.6 GiB** |

> ⚠️ With one workflow per transaction, the index-heavy Postgres visibility table
> (~50 KiB/execution) **dominates total storage** — larger than the event history
> itself. Elasticsearch visibility is far cheaper per execution (~1.9 KiB measured
> on the ES stack) and is worth considering if the workload is one workflow per
> transaction.

**Recommended provisioning (batched model): ~3 GB** (margin for index overhead,
WAL, and the caveats below). For a per-transaction-workflow model, budget ~18–20 GB.

---

## Caveats — factors that move the number

1. **Transaction → workflow mapping is the #1 driver.** Batching amortizes both
   history framing and (especially) the index-heavy visibility row across many items.
2. **Payloads are tiny here.** Activities take an `int` and return a short string.
   Real payloads stored in `history_node` are the second-biggest lever.
3. **Fail rate ~10.3%.** Failed items stop early (shorter history), so the average
   is slightly below a pure all-success run.
4. **Custom search attributes** add more visibility indexes → more per-execution cost.

---

## How to reproduce

```bash
# Stack with Postgres visibility (creates temporal + temporal_visibility DBs)
cd samples-server/compose
docker compose -f docker-compose-postgres.yml up -d

# Baseline (run for BOTH databases, after VACUUM ANALYZE)
docker exec temporal-postgresql psql -U temporal -d temporal -c "VACUUM ANALYZE;"
docker exec temporal-postgresql psql -U temporal -d temporal_visibility -c "VACUUM ANALYZE;"
docker exec temporal-postgresql psql -U temporal -d temporal -At -c \
  "SELECT pg_total_relation_size('history_node'), pg_total_relation_size('executions'), pg_database_size('temporal');"
docker exec temporal-postgresql psql -U temporal -d temporal_visibility -At -c \
  "SELECT pg_total_relation_size('executions_visibility'), pg_database_size('temporal_visibility');"

# Workers (repeat for throughput) + load
BATCH_STEP_SLEEP_MS=0 uv run python -m automation.processes.example_batch_controllable.workers.worker &
uv run python -m automation.processes.example_batch_controllable.clients.starter \
    --total 10000 --batch-size 100 --concurrency 20 --batches-per-run 100 --wait-result

# Re-measure (same queries, after VACUUM ANALYZE)

# Split heap vs indexes for the visibility table:
docker exec temporal-postgresql psql -U temporal -d temporal_visibility -At -c \
  "SELECT pg_table_size('executions_visibility'), pg_indexes_size('executions_visibility');"
```
