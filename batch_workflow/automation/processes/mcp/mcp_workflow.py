"""MCP Workflow — acquires a session on one worker, pins all MCP tool
calls to that worker, and releases on completion.

Handles worker failure mid-workflow by re-acquiring on another worker.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from automation.objects.mcp.activities import (
        acquire_mcp_session,
        call_mcp_tool,
        release_mcp_session,
    )
    from automation.objects.mcp.models import SessionInfo, ToolInput, ToolOutput


@dataclass
class McpWorkflowInput:
    tasks: list[ToolInput]


@workflow.defn
class McpWorkflow:
    @workflow.run
    async def run(self, input: McpWorkflowInput) -> list[ToolOutput]:
        session = await self._acquire()
        results: list[ToolOutput] = []

        try:
            for task in input.tasks:
                try:
                    result = await workflow.execute_activity(
                        call_mcp_tool,
                        task,
                        task_queue=session.task_queue,
                        start_to_close_timeout=timedelta(seconds=60),
                        schedule_to_start_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=2),
                            maximum_interval=timedelta(seconds=10),
                            maximum_attempts=3,
                        ),
                    )
                    results.append(result)

                except ActivityError:
                    # Worker ตายหรือ MCP server ล่ม → release เก่า, acquire ใหม่
                    await self._try_release(session)
                    session = await self._acquire()

                    result = await workflow.execute_activity(
                        call_mcp_tool,
                        task,
                        task_queue=session.task_queue,
                        start_to_close_timeout=timedelta(seconds=60),
                        schedule_to_start_timeout=timedelta(seconds=30),
                    )
                    results.append(result)

        finally:
            await self._try_release(session)

        return results

    async def _acquire(self) -> SessionInfo:
        return await workflow.execute_activity(
            acquire_mcp_session,
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                maximum_attempts=3,
            ),
        )

    async def _try_release(self, session: SessionInfo) -> None:
        try:
            await workflow.execute_activity(
                release_mcp_session,
                task_queue=session.task_queue,
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_start_timeout=timedelta(seconds=10),
            )
        except ActivityError:
            pass  # worker ตายแล้ว → idle watchdog จะ cleanup เอง
