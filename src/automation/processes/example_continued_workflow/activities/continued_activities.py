"""Activities for the continuous dispatcher. All I/O lives here.

``generate_items`` stands in for a real source of new work (a queue, an API, a
table scan). Here it synthesizes the next window of items after ``after_seq``.
Replace the body with real work.
"""

import asyncio

from temporalio import activity

from ..configs.queues import ITEMS_PER_POLL
from ..models.continued import ItemInput


@activity.defn
async def generate_items(after_seq: int) -> list[ItemInput]:
    """Produce the next batch of new items. Deterministic in ``after_seq`` so a
    retry returns the same window (at-least-once safe)."""
    await asyncio.sleep(0.05)  # stand-in for a real fetch/generate call
    return [
        ItemInput(seq=after_seq + i + 1, payload=f"item-{after_seq + i + 1}")
        for i in range(ITEMS_PER_POLL)
    ]


@activity.defn
async def process_item(item: ItemInput) -> bool:
    """Handle one generated item. Replace with real work."""
    await asyncio.sleep(0.05)
    return True
