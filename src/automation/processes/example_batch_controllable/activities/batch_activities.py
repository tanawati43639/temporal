"""Activities for the batch process — all I/O lives here, never in a workflow.

``process_item`` simulates handling one work item, including transient and
permanent failures so Temporal's retry policy is exercised. Replace the body
with real work (DB/API/UI call). Note how it pulls config through a shared
integration rather than reading os.environ directly.
"""

import asyncio

from temporalio import activity

from automation.integrations.secrets.client import get_secret


@activity.defn
async def process_item(item_id: int) -> str:
    """Process one item. Replace with real work."""
    info = activity.info()

    # Config comes from a shared integration (swap env for Vault in prod).
    fail_every = int(get_secret("BATCH_FAIL_EVERY", "17"))
    invalid_every = int(get_secret("BATCH_INVALID_EVERY", "97"))

    # Transient error: fails on the first attempt, so a retry succeeds.
    if fail_every and item_id % fail_every == 0 and info.attempt == 1:
        raise RuntimeError(f"transient error on item {item_id}")

    # Permanent error: fails on every attempt (ValueError is non-retryable below).
    if invalid_every and item_id % invalid_every == 0:
        raise ValueError(f"item {item_id} is invalid")

    await asyncio.sleep(10)  # stand-in for real latency
    return f"item-{item_id}-done"
