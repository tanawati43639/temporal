"""Parent Workflow — fan-out department workflows

รับ list ของ departments → สร้าง DepartmentWorkflow ต่อ dept → รอผลทั้งหมด

3-level fan-out:
  Parent → DepartmentWorkflow (mid) → ProcessCustomerWorkflow (leaf)
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from workflows.department_workflow import DepartmentWorkflow
    from workflows.models import DepartmentResult, FanoutInput


@workflow.defn
class FanoutWorkflow:
    @workflow.run
    async def run(self, input: FanoutInput) -> list[DepartmentResult]:
        workflow.logger.info(
            "Starting fan-out for %d departments", len(input.departments)
        )

        handles = []
        for dept in input.departments:
            handle = await workflow.start_child_workflow(
                DepartmentWorkflow.run,
                dept,
                id=f"department-{dept.department_id}",
                execution_timeout=timedelta(minutes=30),
            )
            handles.append((dept.department_id, handle))

        results: list[DepartmentResult] = []

        async def collect(dept_id: str, handle):
            try:
                result = await handle
                results.append(result)
            except ChildWorkflowError as e:
                results.append(DepartmentResult(
                    department_id=dept_id,
                    error=str(e),
                ))
                workflow.logger.warning("Department %s: failed — %s", dept_id, e)

        await asyncio.gather(*[collect(did, h) for did, h in handles])

        total_customers = sum(len(r.customers) for r in results)
        total_ok = sum(
            1 for r in results for c in r.customers if c.error is None
        )
        workflow.logger.info(
            "Fan-out complete: %d departments, %d customers (%d success)",
            len(results), total_customers, total_ok,
        )
        return results
