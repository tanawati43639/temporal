"""Parent Workflow — fan-out child workflows

รับ list ของ customer_ids → สร้าง child workflow ต่อคน → รอผลทั้งหมด

Fan-out pattern:
  - start child workflows พร้อมกัน (async)
  - รอ result ทั้งหมดกลับมา
  - child ที่ fail → จับ error ไว้ ไม่ block ตัวอื่น
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from workflows.child_workflow import ProcessCustomerWorkflow
    from workflows.models import CustomerResult, FanoutInput


@workflow.defn
class FanoutWorkflow:
    @workflow.run
    async def run(self, input: FanoutInput) -> list[CustomerResult]:
        workflow.logger.info(
            "Starting fan-out for %d customers", len(input.customer_ids)
        )

        # Start ทุก child workflow พร้อมกัน
        handles = []
        for cid in input.customer_ids:
            handle = await workflow.start_child_workflow(
                ProcessCustomerWorkflow.run,
                cid,
                id=f"process-customer-{cid}",
                execution_timeout=timedelta(minutes=10),
            )
            handles.append((cid, handle))

        # รอผลทุกตัว — ตัวที่ fail ไม่ block ตัวอื่น
        results: list[CustomerResult] = []

        async def collect(customer_id: str, handle):
            try:
                result = await handle
                results.append(result)
                workflow.logger.info("Customer %s: done", customer_id)
            except ChildWorkflowError as e:
                results.append(CustomerResult(
                    customer_id=customer_id,
                    error=str(e),
                ))
                workflow.logger.warning("Customer %s: failed — %s", customer_id, e)

        await asyncio.gather(*[
            collect(cid, handle) for cid, handle in handles
        ])

        workflow.logger.info(
            "Fan-out complete: %d success, %d failed",
            sum(1 for r in results if r.error is None),
            sum(1 for r in results if r.error is not None),
        )
        return results
