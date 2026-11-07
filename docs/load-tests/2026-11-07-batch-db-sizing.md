# Load Test: Temporal DB Sizing — Controllable Batch

**Date:** 2026-11-07
**Process under test:** `example_batch_controllable`
**Goal:** Measure how much Postgres storage one transaction consumes, so we can
size the database for a **60-day retention** window.

---

## TL;DR

| Metric | Value |
|---|---:|
| Transactions run | 10,000 items (100,000 activity executions) |
| Outcome | processed 8,970 / failed 1,030 |
| **Retained storage per transaction** | **~8.4 KiB** (`history_node` + `executions` = 8,572 bytes) |
| Prediction for **260,000** transactions | **~2.1 GiB** (provision ~3 GB with margin) |

> Use **retained-per-transaction (8.4 KiB)** for retention projections — not the
> raw DB-total growth, which includes transient task-table bloat that scales with
> concurrency, not with retained volume.

---

## Environment

| Component | Value |
|---|---|
| Temporal server | `temporalio/server:1.31.0` (Docker Compose, `localhost:7233`) |
| Persistence | `postgres:16` (`temporal-postgresql`), single DB `temporal` |
| Visibility | Elasticsearch 7.17 (`temporal-elasticsearch`) — **not** measured here |
| Namespace | `default` |
| Python SDK | `temporalio` 1.35.0 |

Note: visibility lives in Elasticsearch, **not** Postgres, so this report covers
only the Postgres history/state store.

---

## Workload definition

`example_batch_controllable` was extended into a **10-step pipeline per item**:

- Each item flows through activities `step_01` … `step_10` **in sequence**.
- Success/failure is **deterministic**, driven by config (never by workflow input)
  so the test is reproducible. For `key = item_id * 10 + step_no`:
  - **Transient** failure (retryable `RuntimeError`) when `key % BATCH_FAIL_EVERY == 0`
    on the first attempt → retry succeeds (adds extra history events).
  - **Permanent** failure (non-retryable `ValueError`) when `key % BATCH_INVALID_EVERY == 0`
    → the item's pipeline stops there and the item is counted failed.
- Per-step latency comes from config `BATCH_STEP_SLEEP_MS` (set to `0` for this
  test — latency does not affect history size, only wall-clock).

Config used (defaults): `BATCH_FAIL_EVERY=17`, `BATCH_INVALID_EVERY=97`, `BATCH_STEP_SLEEP_MS=0`.

The 1,030 failures match the formula exactly: there are 1,030 keys in `1..100000`
divisible by 97, and each lands in a distinct item (10 consecutive keys per item
contain at most one multiple of 97).

---

## Method

1. `VACUUM ANALYZE`, then record baseline sizes (`pg_total_relation_size`, `pg_database_size`).
2. Start **6 worker processes** (`BATCH_STEP_SLEEP_MS=0`, `MAX_CONCURRENT_ACTIVITIES=10` each).
3. Start one parent workflow: `--total 10000 --batch-size 100 --concurrency 20 --batches-per-run 100`
   (completes in a single run, no continue-as-new).
4. Wait for completion (`--wait-result`).
5. `VACUUM ANALYZE`, record sizes again.
6. Diff per table + total; divide by 10,000 for per-transaction cost.

`VACUUM` before each measurement keeps dead-tuple bloat from skewing the numbers.

---

## Results

### Size before vs after (VACUUM'd both times)

| Table | Before | After | Diff | KiB/txn |
|---|---:|---:|---:|---:|
| `history_node` (events) | 3.71 MiB | 81.43 MiB | **+77.72 MiB** | 7.96 |
| `executions` (mutable state) | 0.46 MiB | 4.49 MiB | **+4.03 MiB** | 0.41 |
| `history_tree` | 0.38 MiB | 0.38 MiB | +0.00 | 0.00 |
| **DB total (`temporal`)** | 15.33 MiB | 117.28 MiB | **+101.95 MiB** | 10.44 |

`history_node` grew by **137,838 rows** (~13.8 rows/txn — event history is chunked
across nodes).

### Why DB total (+101.95 MiB) exceeds the two tables (+81.75 MiB)

The ~20 MiB gap is **transient task tables** that inflate during the run and are
then emptied (VACUUM marks pages reusable but does not return them to the OS):

| Table | Size after | Live rows |
|---|---:|---:|
| `timer_tasks` | 10.0 MiB | 1,906 |
| `tasks` | 6.6 MiB | 280 |
| `activity_info_maps` | 3.6 MiB | **0** |
| `transfer_tasks` | 1.3 MiB | **0** |

These scale with **in-flight concurrency, not retained transaction count**, so they
are roughly a fixed high-water overhead (~16 MiB here) and must **not** be
multiplied across a retention window.

---

## Per-transaction cost

```
retained per txn = history_node + executions
                 = 8,149 B + 423 B
                 = 8,572 B  (≈ 8.37 KiB)
```

---

## Prediction: 260,000 transactions (same profile)

| Component | Size |
|---|---:|
| `history_node` | 1.97 GiB (2.12 GB) |
| `executions` | 105 MiB |
| **Retained subtotal** | **2.08 GiB (2.23 GB)** |
| + fixed task-table overhead | ~16 MiB |
| **= estimate** | **≈ 2.1 GiB (~2.25 GB)** |

**Recommended provisioning: ~3 GB** (adds margin for index overhead, WAL, and the
not-yet-measured items below).

---

## Caveats — factors that move the number

1. **Elasticsearch visibility is not included.** Adds ~1 record per workflow
   execution in a separate store. Usually much smaller than history, but must be added.
2. **Payloads are tiny here.** Activities take an `int` and return a short string.
   Real payloads stored in `history_node` are the single biggest lever — larger
   payloads scale storage up directly.
3. **Fail rate ~10.3%.** Failed items stop early (shorter history), so the average
   is slightly below a pure all-success run. Lower production failure rates → a bit
   more storage per transaction.
4. **Grouping (`batch_size=100`).** Changes how parent/child framing overhead
   amortizes per item (minor effect).

---

## How to reproduce

```bash
# 1. Baseline
docker exec temporal-postgresql psql -U temporal -d temporal -c "VACUUM ANALYZE;"
docker exec temporal-postgresql psql -U temporal -d temporal -At -F'|' -c "
SELECT 'history_node', pg_total_relation_size('history_node')
UNION ALL SELECT 'executions', pg_total_relation_size('executions')
UNION ALL SELECT 'DB_TOTAL', pg_database_size('temporal');"

# 2. Workers (repeat N times for throughput)
BATCH_STEP_SLEEP_MS=0 uv run python -m automation.processes.example_batch_controllable.workers.worker &

# 3. Load
uv run python -m automation.processes.example_batch_controllable.clients.starter \
    --total 10000 --batch-size 100 --concurrency 20 --batches-per-run 100 --wait-result

# 4. Re-measure (same queries as step 1, after VACUUM ANALYZE)
```
