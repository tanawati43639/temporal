"""High-level helpers for credential pool — use from any workflow.

These wrap the child-workflow / signal dance into simple async calls::

    from automation.common.credential_pool import acquire_credential, release_credential

    cred = await acquire_credential("SAP_POOL")
    # ... use cred ...
    await release_credential("SAP_POOL", cred.name)

IMPORTANT: the calling workflow's worker must register both
``CredentialPoolWorkflow`` and ``AcquireCredentialWorkflow`` (or use
the shared credential-pool worker).
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

from automation.common.credential_pool.models.pool import (
    AcquireFromPoolInput,
    CredentialInfo,
    ReleaseSignal,
)
from automation.common.credential_pool.workflows.acquire import AcquireCredentialWorkflow


async def acquire_credential(
    pool_name: str,
    *,
    timeout_seconds: int = 300,
    child_id_suffix: str = "acquire",
) -> CredentialInfo:
    """Acquire a credential from a named pool.

    Starts a child ``AcquireCredentialWorkflow`` that signals the pool
    manager and waits for the grant.  Returns the ``CredentialInfo``
    with ``.name``, ``.username``, ``.password``.
    """
    caller_id = workflow.info().workflow_id
    child_id = f"{caller_id}-{child_id_suffix}"

    return await workflow.execute_child_workflow(
        AcquireCredentialWorkflow.run,
        AcquireFromPoolInput(
            pool_name=pool_name,
            timeout_seconds=timeout_seconds,
        ),
        id=child_id,
        task_queue=workflow.info().task_queue,
        execution_timeout=timedelta(seconds=timeout_seconds + 60),
    )


async def release_credential(pool_name: str, credential_name: str) -> None:
    """Release a credential back to the pool."""
    caller_id = workflow.info().workflow_id
    pool_wf_id = f"cred-pool-{pool_name}"

    pool_handle = workflow.get_external_workflow_handle(pool_wf_id)
    await pool_handle.signal(
        "release",
        ReleaseSignal(
            requester_workflow_id=f"{caller_id}-acquire",
            credential_name=credential_name,
        ),
    )
