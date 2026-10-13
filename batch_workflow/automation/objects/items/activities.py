"""Item object — the Temporal equivalent of a Blue Prism VBO.

All I/O (API/DB/UI calls) lives in activities. This one simulates processing a
single work-queue item, including transient and permanent failures so Temporal's
retry policy is exercised.
"""

import asyncio

from temporalio import activity


@activity.defn
async def process_item(item_id: int) -> str:
    """Process one item. Replace with real work (DB/API call, etc.)."""

    info = activity.info()

    # Custom worker-side metric: count every outcome, tagged by attempt number
    # so retries are visible. Emitted on the SDK Prometheus endpoint alongside
    # the built-in metrics, as batch_items_processed_total{outcome,attempt}.
    outcomes = activity.metric_meter().create_counter(
        "batch_items_processed",
        description="Items handled by the worker, by outcome and attempt",
    )

    # Simulate a transient error: some items fail on the first attempt
    # so Temporal's retry policy kicks in.
    if item_id % 17 == 0 and info.attempt == 1:
        outcomes.add(1, {"outcome": "transient_error", "attempt": str(info.attempt)})
        raise RuntimeError(f"transient error on item {item_id}")

    # Simulate a permanent error: these items fail on every attempt.
    if item_id % 97 == 0:
        outcomes.add(1, {"outcome": "permanent_error", "attempt": str(info.attempt)})
        raise ValueError(f"item {item_id} is invalid")

    await asyncio.sleep(30)
    outcomes.add(1, {"outcome": "success", "attempt": str(info.attempt)})
    return f"item-{item_id}-done"
