"""API registration for the credential-lock slice."""

from __future__ import annotations

from pydantic import BaseModel, Field

from automation.api.spec import QuerySpec, SignalSpec, WorkflowSpec

from .configs.queues import CREDENTIAL_LOCK_QUEUE, LOCK_TIMEOUT_SECONDS
from .models.credential import AcquireRequest, LockManagerInput, ReleaseRequest
from .workflows.lock_manager import CredentialLockWorkflow


class StartCredentialLockRequest(BaseModel):
    credential_name: str = Field(description="Name of the credential to manage")
    lock_timeout_seconds: int = Field(
        default=LOCK_TIMEOUT_SECONDS,
        description="Auto-release timeout in seconds",
    )


class AcquireLockRequest(BaseModel):
    requester_workflow_id: str = Field(description="Workflow ID requesting the lock")
    credential_name: str = Field(default="", description="Credential name (for reference)")
    timeout_seconds: int = Field(default=300, description="Lock timeout in seconds")


class ReleaseLockRequest(BaseModel):
    requester_workflow_id: str = Field(description="Workflow ID releasing the lock")


def _input_builder(r: StartCredentialLockRequest) -> LockManagerInput:
    return LockManagerInput(
        credential_name=r.credential_name,
        lock_timeout_seconds=r.lock_timeout_seconds,
    )


SPECS: list[WorkflowSpec] = [
    WorkflowSpec(
        name="credential-lock",
        display_name="Credential Lock",
        description=(
            "Semaphore-based credential lock manager — ensures only one "
            "workflow at a time can use a given credential (like Blue Prism "
            "Acquire Lock)"
        ),
        workflow_class=CredentialLockWorkflow,
        run_method=CredentialLockWorkflow.run,
        task_queue=CREDENTIAL_LOCK_QUEUE,
        id_prefix="cred-lock",
        start_body_model=StartCredentialLockRequest,
        start_input_builder=_input_builder,
        signals={
            "acquire": SignalSpec(
                CredentialLockWorkflow.acquire,
                body_model=AcquireLockRequest,
                description="Request exclusive lock on the credential",
            ),
            "release": SignalSpec(
                CredentialLockWorkflow.release,
                body_model=ReleaseLockRequest,
                description="Release the credential lock",
            ),
            "shutdown": SignalSpec(
                CredentialLockWorkflow.shutdown,
                description="Gracefully shut down the lock manager",
            ),
        },
        queries={
            "status": QuerySpec(
                CredentialLockWorkflow.status,
                description="Current lock holder, queue, and stats",
            ),
        },
    ),
]
