"""AcquireCredentialWorkflow — child workflow that acquires from a pool.

This is the "activity-like" wrapper.  A caller starts it as a child
workflow and awaits the result — just like calling an activity:

    cred = await workflow.execute_child_workflow(
        AcquireCredentialWorkflow.run,
        AcquireFromPoolInput(pool_name="SAP_POOL"),
        id=f"{workflow.info().workflow_id}-acquire",
    )
    # cred is a CredentialInfo with .name, .username, .password

Internally, this workflow:
  1. Signals the pool manager to acquire
  2. Waits for the ``credential_granted`` signal back
  3. Returns the CredentialInfo to the caller
"""

from __future__ import annotations

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from automation.common.credential_pool.models.pool import (
        AcquireFromPoolInput,
        AcquireSignal,
        CredentialInfo,
        GrantedSignal,
    )


@workflow.defn
class AcquireCredentialWorkflow:

    def __init__(self) -> None:
        self._granted: GrantedSignal | None = None

    @workflow.signal
    async def credential_granted(self, grant: GrantedSignal) -> None:
        self._granted = grant

    @workflow.query
    def status(self) -> str:
        if self._granted:
            return f"granted:{self._granted.credential_name}"
        return "waiting"

    @workflow.run
    async def run(self, input: AcquireFromPoolInput) -> CredentialInfo:
        my_id = workflow.info().workflow_id
        pool_wf_id = f"cred-pool-{input.pool_name}"

        pool_handle = workflow.get_external_workflow_handle(pool_wf_id)
        await pool_handle.signal(
            "acquire",
            AcquireSignal(requester_workflow_id=my_id),
        )

        await workflow.wait_condition(lambda: self._granted is not None)

        return CredentialInfo(
            name=self._granted.credential_name,
            username=self._granted.username,
            password=self._granted.password,
        )
