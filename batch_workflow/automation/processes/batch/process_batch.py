"""ProcessBatchWorkflow — child process that handles one batch of items.

A Process (workflow) is deterministic orchestration only: it calls objects
(activities), never does I/O itself.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from automation.models.batch import BatchInput, BatchResult
    from automation.objects.items.activities import process_item


@workflow.defn
class ProcessBatchWorkflow:
    """Child workflow: process every item in one batch."""

    @workflow.run
    async def run(self, input: BatchInput) -> BatchResult:
        async def run_one(item_id: int) -> bool:
            try:
                await workflow.execute_activity(
                    process_item,
                    item_id,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        maximum_attempts=3,
                        non_retryable_error_types=["ValueError"],
                    ),
                )
                return True
            except ActivityError:
                workflow.logger.warning("Item %s failed", item_id)
                return False

        item_ids = list(range(input.start, input.end))
        results = await asyncio.gather(*(run_one(i) for i in item_ids))

        failed_items = [i for i, ok in zip(item_ids, results) if not ok]
        return BatchResult(
            batch_id=input.batch_id,
            processed=len(item_ids) - len(failed_items),
            failed=len(failed_items),
            failed_items=failed_items,
        )
