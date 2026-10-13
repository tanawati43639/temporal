"""BatchParentWorkflow — parent process that splits work into batches and fans
out to child processes, then continues-as-new to keep history small.
"""

import asyncio

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from automation.models.batch import BatchInput, BatchResult, BatchSummary, ParentInput
    from automation.processes.batch.process_batch import ProcessBatchWorkflow


@workflow.defn
class BatchParentWorkflow:
    """Parent workflow: split work into batches and fan out to child workflows."""

    def __init__(self) -> None:
        self._input: ParentInput | None = None

    @workflow.run
    async def run(self, input: ParentInput) -> BatchSummary:
        self._input = input
        parent_id = workflow.info().workflow_id
        batches_this_run = 0

        while (
            input.next_offset < input.total_items
            and batches_this_run < input.batches_per_run
        ):
            # Build the next window of up to max_concurrent_children batches
            window: list[BatchInput] = []
            offset = input.next_offset
            while (
                offset < input.total_items
                and len(window) < input.max_concurrent_children
                and batches_this_run + len(window) < input.batches_per_run
            ):
                end = min(offset + input.batch_size, input.total_items)
                window.append(
                    BatchInput(batch_id=offset // input.batch_size, start=offset, end=end)
                )
                offset = end

            results: list[BatchResult] = await asyncio.gather(
                *(
                    workflow.execute_child_workflow(
                        ProcessBatchWorkflow.run,
                        batch,
                        # Deterministic ID: stays the same across retries and continue-as-new
                        id=f"{parent_id}-batch-{batch.batch_id}",
                    )
                    for batch in window
                )
            )

            for r in results:
                input.processed += r.processed
                input.failed += r.failed
            input.next_offset = offset
            batches_this_run += len(window)

        if input.next_offset < input.total_items:
            workflow.logger.info(
                "Continue-as-new at offset %s/%s", input.next_offset, input.total_items
            )
            workflow.continue_as_new(input)

        return BatchSummary(
            total_items=input.total_items,
            processed=input.processed,
            failed=input.failed,
        )

    @workflow.query
    def progress(self) -> dict:
        if self._input is None:
            return {}
        return {
            "total_items": self._input.total_items,
            "next_offset": self._input.next_offset,
            "processed": self._input.processed,
            "failed": self._input.failed,
        }
