"""ExampleItemWorkflow — child that processes one generated item.

Started by the dispatcher with ParentClosePolicy.ABANDON, so it keeps running
even when the parent continue-as-news.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from automation.processes.example_continued_workflow.activities.continued_activities import (
        process_item,
    )
    from automation.processes.example_continued_workflow.models.continued import (
        ItemInput,
        ItemResult,
    )


@workflow.defn
class ExampleItemWorkflow:
    @workflow.run
    async def run(self, item: ItemInput) -> ItemResult:
        ok = await workflow.execute_activity(
            process_item,
            item,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return ItemResult(seq=item.seq, ok=ok)
