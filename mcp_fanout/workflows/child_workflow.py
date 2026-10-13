"""Child Workflow — ประมวลผลลูกค้า 1 คน

  fetch_customer → enrich_profile → send_notification

ใช้ call_mcp_tool ตัวเดียว ส่ง tool_name + args เข้าไป
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows.activities import call_mcp_tool
    from workflows.models import CustomerResult, ToolInput

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
            call_mcp_tool,
            ToolInput(tool_name="fetch_customer", args={"customer_id": customer_id}),
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RETRY,
        )

        customer_data = fetched.result

        # 2. Enrich profile
        enriched = await workflow.execute_activity(
            call_mcp_tool,
            ToolInput(tool_name="enrich_profile", args={"customer": customer_data}),
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RETRY,
        )

        # 3. ส่ง notification
        notified = await workflow.execute_activity(
            call_mcp_tool,
            ToolInput(
                tool_name="send_notification",
                args={
                    "email": customer_data["email"],
                    "subject": f"Profile updated: {customer_data['name']}",
                    "body": f"Hi {customer_data['name']}, your profile has been enriched.",
                },
            ),
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RETRY,
        )

        return CustomerResult(
            customer_id=customer_id,
            profile=enriched.result,
            notification=notified.result,
        )
