"""Department Workflow — mid-level fan-out

รับ department_id + customer_ids → fan-out child workflow ต่อคน → รวมผล
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from workflows.child_workflow import ProcessCustomerWorkflow
    from workflows.models import CustomerResult, DepartmentInput, DepartmentResult


@workflow.defn
class DepartmentWorkflow:
    @workflow.run
    async def run(self, input: DepartmentInput) -> DepartmentResult:
        workflow.logger.info(
            "Department %s: processing %d customers",
            input.department_id, len(input.customer_ids),
        )

        handles = []
        for cid in input.customer_ids:
            handle = await workflow.start_child_workflow(
                ProcessCustomerWorkflow.run,
                cid,
                id=f"dept-{input.department_id}-customer-{cid}",
                execution_timeout=timedelta(minutes=10),
            )
            handles.append((cid, handle))

        results: list[CustomerResult] = []

        async def collect(customer_id: str, handle):
            try:
                result = await handle
                results.append(result)
            except ChildWorkflowError as e:
                results.append(CustomerResult(
                    customer_id=customer_id,
                    error=str(e),
                ))
                workflow.logger.warning(
                    "Department %s, customer %s: failed — %s",
                    input.department_id, customer_id, e,
                )

        await asyncio.gather(*[collect(cid, h) for cid, h in handles])

        workflow.logger.info(
            "Department %s done: %d success, %d failed",
            input.department_id,
            sum(1 for r in results if r.error is None),
            sum(1 for r in results if r.error is not None),
        )
        return DepartmentResult(
            department_id=input.department_id,
            customers=results,
        )
