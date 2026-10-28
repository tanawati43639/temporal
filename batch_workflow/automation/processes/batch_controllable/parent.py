"""ControllableBatchParentWorkflow — fan-out parent with pause/resume/stop.

Extends the plain BatchParentWorkflow with three signals and a status query:

    request_pause   — hold at the next window boundary (in-flight children
                      finish; no new windows start).
    request_resume  — clear the pause flag.
    request_stop    — graceful halt: finish any in-flight window, then return
                      the current summary (no continue-as-new).

Pause granularity is the fan-out window boundary (one window =
``max_concurrent_children`` child workflows). To pause mid-batch, shrink
``batch_size`` or forward the signals to in-flight children with
``workflow.get_external_workflow_handle(child_id).signal(...)``.
"""

import asyncio

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from automation.models.batch import BatchInput, BatchResult, BatchSummary, ParentInput
    from automation.processes.batch.process_batch import ProcessBatchWorkflow


@workflow.defn
class ControllableBatchParentWorkflow:
    """Parent workflow that fans out to children and honors pause/resume/stop."""

    def __init__(self) -> None:
        self._input: ParentInput | None = None
        self._paused = False
        self._stop_requested = False
        # True while the main loop is actually sitting at the pause boundary
        # (no window being launched). Flipped by run() around wait_condition.
        self._at_pause_boundary = False

    @workflow.signal
    def request_pause(self) -> None:
        workflow.logger.info("request_pause received")
        self._paused = True

    @workflow.update
    async def pause_and_wait(self) -> dict:
        """Pause and block the caller until the parent actually reaches the
        pause boundary (in-flight window finished, no new window launched).

        Returns the progress snapshot captured at the pause point.
        """
        self._paused = True
        await workflow.wait_condition(
            lambda: self._at_pause_boundary or self._stop_requested
        )
        return self.progress()

    @workflow.signal
    def request_resume(self) -> None:
        workflow.logger.info("request_resume received")
        self._paused = False

    @workflow.signal
    def request_stop(self) -> None:
        workflow.logger.info("request_stop received")
        self._stop_requested = True
        # Unblock any pending pause so the main loop can exit promptly.
        self._paused = False

    @workflow.query
    def state(self) -> str:
        if self._stop_requested:
            return "stopping"
        if self._paused:
            return "paused"
        return "running"

    @workflow.query
    def progress(self) -> dict:
        if self._input is None:
            return {"state": self.state()}
        return {
            "state": self.state(),
            "total_items": self._input.total_items,
            "next_offset": self._input.next_offset,
            "processed": self._input.processed,
            "failed": self._input.failed,
        }

    @workflow.run
    async def run(self, input: ParentInput) -> BatchSummary:
        self._input = input
        parent_id = workflow.info().workflow_id
        batches_this_run = 0

        while (
            input.next_offset < input.total_items
            and batches_this_run < input.batches_per_run
            and not self._stop_requested
        ):
            # Pause boundary: block here until resumed or stopped. This is
            # durable — a pause that outlives the worker still holds on replay.
            # _at_pause_boundary lets `pause_and_wait` confirm we actually
            # reached the hold point before replying to its caller.
            if self._paused:
                self._at_pause_boundary = True
            await workflow.wait_condition(
                lambda: not self._paused or self._stop_requested
            )
            self._at_pause_boundary = False
            if self._stop_requested:
                break

            # Build the next window of up to max_concurrent_children batches.
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

            # Deterministic child IDs: same across retries and continue-as-new.
            results: list[BatchResult] = await asyncio.gather(
                *(
                    workflow.execute_child_workflow(
                        ProcessBatchWorkflow.run,
                        batch,
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

        if self._stop_requested:
            workflow.logger.info(
                "Stopped at offset %s/%s", input.next_offset, input.total_items
            )
        elif input.next_offset < input.total_items:
            # Honor pause before continue-as-new. Without this, a pause that
            # arrives after the batches_per_run cap is reached would be lost:
            # the loop exits before touching wait_condition, continue_as_new
            # fires, and the next execution starts with _paused=False.
            if self._paused:
                self._at_pause_boundary = True
                await workflow.wait_condition(
                    lambda: not self._paused or self._stop_requested
                )
                self._at_pause_boundary = False
            if self._stop_requested:
                workflow.logger.info(
                    "Stopped before continue-as-new at offset %s/%s",
                    input.next_offset,
                    input.total_items,
                )
            else:
                workflow.logger.info(
                    "Continue-as-new at offset %s/%s",
                    input.next_offset,
                    input.total_items,
                )
                workflow.continue_as_new(input)

        return BatchSummary(
            total_items=input.total_items,
            processed=input.processed,
            failed=input.failed,
        )
