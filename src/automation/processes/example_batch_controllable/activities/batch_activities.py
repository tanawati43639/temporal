"""Activities for the batch process — all I/O lives here, never in a workflow.

This process models a **10-step pipeline per item**: each work item flows
through ``step_01`` .. ``step_10`` in order. Every step simulates work and can
fail, so Temporal's retry policy is exercised and the Event History grows ~10x
versus a single activity — useful for load-testing how much database storage a
given retention window needs.

Failures are **deterministic** and driven entirely by config (never by workflow
input), so a load test is reproducible: the same item/step always fails the same
way. Replace the body with real work (DB/API/UI call) to adapt this to a real
pipeline. Note how config is pulled through a shared integration rather than
reading os.environ directly.
"""

import asyncio

from temporalio import activity

from automation.integrations.secrets.client import get_secret

# Number of pipeline steps each item flows through.
PIPELINE_STEPS = 10


async def _run_step(item_id: int, step_no: int) -> str:
    """Run one pipeline step for one item.

    Shared by every ``step_NN`` activity so the per-step logic lives in one
    place. ``step_no`` is 1-based (1..PIPELINE_STEPS).
    """
    info = activity.info()

    # Tuning comes from config (swap env for Vault in prod), never from input.
    fail_every = int(get_secret("BATCH_FAIL_EVERY", "17"))
    invalid_every = int(get_secret("BATCH_INVALID_EVERY", "97"))
    sleep_ms = int(get_secret("BATCH_STEP_SLEEP_MS", "100"))

    # Unique deterministic key per (item, step) so success/fail is spread across
    # the pipeline instead of hitting the same step every time.
    key = item_id * PIPELINE_STEPS + step_no

    # Transient error: fails on the first attempt only, so a retry succeeds
    # (adds extra events to history — more load per item).
    if fail_every and key % fail_every == 0 and info.attempt == 1:
        raise RuntimeError(f"transient error on item {item_id} step {step_no}")

    # Permanent error: fails on every attempt (ValueError is non-retryable in
    # the workflow's retry policy), so the item's pipeline stops here.
    if invalid_every and key % invalid_every == 0:
        raise ValueError(f"item {item_id} step {step_no} is invalid")

    await asyncio.sleep(sleep_ms / 1000)  # stand-in for real latency
    return f"item-{item_id}-step-{step_no:02d}-done"


def _make_step(step_no: int):
    """Build one ``step_NN`` activity that delegates to ``_run_step``.

    Each gets a distinct Temporal activity name (``step_01`` .. ``step_10``) so
    they register and appear in history as separate activity types.
    """

    @activity.defn(name=f"step_{step_no:02d}")
    async def step(item_id: int) -> str:
        return await _run_step(item_id, step_no)

    return step


# Ordered pipeline the workflow walks per item, and the worker registers.
PIPELINE = [_make_step(n) for n in range(1, PIPELINE_STEPS + 1)]
