"""ExampleContinuedWorkflow — continuous dispatcher.

Loops: generate the next window of items (activity) → spawn a child per item →
durable-sleep one interval → repeat, until the deadline or a stop signal. After
``ITERATIONS_PER_RUN`` polls it continue-as-news (carrying ``next_seq`` and the
running count) so history stays bounded no matter how far off the deadline is.

Correctness points:
  - deadline is compared with ``workflow.now()`` (replay-safe), never
    ``datetime.now()``;
  - children start with ``ParentClosePolicy.ABANDON`` so they survive CAN;
  - in-flight handlers are drained before ``continue_as_new``.
"""

import asyncio
from datetime import datetime, timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from automation.processes.example_continued_workflow.activities.continued_activities import (
        generate_items,
    )
    from automation.processes.example_continued_workflow.configs.queues import (
        ITERATIONS_PER_RUN,
        POLL_INTERVAL_SECONDS,
    )
    from automation.processes.example_continued_workflow.models.continued import (
        ContinuedInput,
        ContinuedSummary,
    )
    from automation.processes.example_continued_workflow.workflows.item import (
        ExampleItemWorkflow,
    )

from temporalio.common import RetryPolicy


@workflow.defn
class ExampleContinuedWorkflow:
    def __init__(self) -> None:
        self._stop = False
        self._next_seq = 0
        self._generated = 0

    @workflow.signal
    def request_stop(self) -> None:
        workflow.logger.info("request_stop received")
        self._stop = True

    @workflow.query
    def state(self) -> str:
        return "stopping" if self._stop else "running"

    @workflow.query
    def progress(self) -> dict:
        return {
            "state": self.state(),
            "generated": self._generated,
            "next_seq": self._next_seq,
        }

    @workflow.run
    async def run(self, input: ContinuedInput) -> ContinuedSummary:
        self._next_seq = input.next_seq
        self._generated = input.generated
        deadline = datetime.fromisoformat(input.stop_time)
        parent_id = workflow.info().workflow_id
        iterations = 0

        while (
            workflow.now() < deadline
            and not self._stop
            and iterations < ITERATIONS_PER_RUN
        ):
            items = await workflow.execute_activity(
                generate_items,
                self._next_seq,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            for item in items:
                # ABANDON so the child survives this parent's continue-as-new.
                await workflow.start_child_workflow(
                    ExampleItemWorkflow.run,
                    item,
                    id=f"{parent_id}-item-{item.seq}",
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                self._next_seq = item.seq
                self._generated += 1
            iterations += 1

            # Durable sleep until the next poll, but wake early if stopped.
            try:
                await workflow.wait_condition(
                    lambda: self._stop,
                    timeout=timedelta(seconds=POLL_INTERVAL_SECONDS),
                )
            except asyncio.TimeoutError:
                pass

        # Per-run cap reached but neither deadline nor stop → carry state forward.
        if workflow.now() < deadline and not self._stop:
            await workflow.wait_condition(workflow.all_handlers_finished)
            workflow.continue_as_new(
                ContinuedInput(
                    stop_time=input.stop_time,
                    next_seq=self._next_seq,
                    generated=self._generated,
                )
            )

        return ContinuedSummary(
            generated=self._generated,
            reason="stopped" if self._stop else "deadline",
        )
