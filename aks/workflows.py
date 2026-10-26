"""ตัวอย่าง workflow — สลับเป็น workflow จริงของคุณได้เลย."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import call_api


@workflow.defn
class ApiWorkflow:
    @workflow.run
    async def run(self, url: str) -> dict:
        return await workflow.execute_activity(
            call_api,
            url,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
            ),
        )
