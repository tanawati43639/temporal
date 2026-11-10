"""API registration for this process — the one file the registry discovers.

Exports ``SPECS``: the list of WorkflowSpec this process exposes over REST.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from automation.api.spec import QuerySpec, WorkflowSpec

from .configs.queues import AUDIT_LOG_QUEUE
from .models.audit import AuditInput
from .workflows.audit_log import AuditLogWorkflow


class StartAuditLogRequest(BaseModel):
    lookback_days: int = Field(description="Number of days to look back")
    namespace_filter: list[str] | None = Field(
        default=None,
        description="Namespaces to scan (all if omitted)",
    )


def _input_builder(r: StartAuditLogRequest) -> AuditInput:
    return AuditInput(
        lookback_days=r.lookback_days,
        namespace_filter=r.namespace_filter,
    )


SPECS: list[WorkflowSpec] = [
    WorkflowSpec(
        name="audit-log",
        display_name="Audit Log",
        description="Scan workflow history to collect who started/signaled/terminated workflows",
        workflow_class=AuditLogWorkflow,
        run_method=AuditLogWorkflow.run,
        task_queue=AUDIT_LOG_QUEUE,
        id_prefix="audit",
        start_body_model=StartAuditLogRequest,
        start_input_builder=_input_builder,
        queries={
            "progress": QuerySpec(
                AuditLogWorkflow.progress,
                description="Namespaces completed + total entries so far",
            ),
        },
    ),
]
