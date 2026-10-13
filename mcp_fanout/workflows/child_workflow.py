"""Child Workflow — ประมวลผลลูกค้า 1 คน

  fetch_customer → enrich_profile → send_notification

แต่ละ activity อาจไปลง worker คนละตัว — ไม่มีปัญหา
เพราะทุก worker lazy-start MCP server เอง
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows.activities import (
        enrich_profile,
        fetch_customer,
        send_notification,
    )
    from workflows.models import CustomerResult

RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=5,
)


@workflow.defn
class ProcessCustomerWorkflow:
    @workflow.run
    async def run(self, customer_id: str) -> CustomerResult:
        # 1. ดึงข้อมูลลูกค้า
        fetched = await workflow.execute_activity(
            fetch_customer,
            customer_id,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RETRY,
        )

        customer_data = fetched.result

        # 2. Enrich profile
        enriched = await workflow.execute_activity(
            enrich_profile,
            customer_data,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RETRY,
        )

        # 3. ส่ง notification
        notified = await workflow.execute_activity(
            send_notification,
            args=[customer_data["email"], customer_data["name"]],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RETRY,
        )

        return CustomerResult(
            customer_id=customer_id,
            profile=enriched.result,
            notification=notified.result,
        )
