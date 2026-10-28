"""Workflow registry — single source of truth for the auto-generated API.

Add a new workflow = add one entry to WORKFLOWS. The factory will:
  - mount /api/{name}/start with a typed Pydantic form
  - mount /api/{name}/{id}/status that runs every declared query
  - mount /api/{name}/{id}/signals/{name} per declared signal
  - mount /api/{name}/{id}/updates/{name} per declared update
  - mount /api/{name}/{id}/cancel and /terminate (every workflow)
  - mount /api/{name}  (list) filtered by WorkflowType

Each spec carries only workflow-specific info — the factory handles the
boilerplate once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from automation.config.queues import BATCH_QUEUE, MCP_SHARED_QUEUE
from automation.models.approval import ApprovalDecision, ApprovalRequest
from automation.models.batch import ParentInput
from automation.models.notify import NotifyInput
from automation.processes.approval.approval_workflow import ApprovalWorkflow
from automation.processes.batch.parent import BatchParentWorkflow
from automation.processes.batch_controllable.parent import (
    ControllableBatchParentWorkflow,
)
from automation.processes.mcp.mcp_workflow import McpWorkflow, McpWorkflowInput
from automation.processes.notify.notify_workflow import NotifyWorkflow
from automation.objects.mcp.models import ToolInput

from .schemas import (
    DecideRequest,
    McpToolInputModel,
    StartApprovalRequest,
    StartBatchRequest,
    StartControllableBatchRequest,
    StartMcpRequest,
    StartNotifyRequest,
    UpdateAmountRequest,
)


# ─── per-interaction specs ─────────────────────────────────────────
@dataclass
class SignalSpec:
    """One signal exposed via REST."""

    fn: Any  # unbound method on the workflow class
    body_model: type[BaseModel] | None = None  # None = no payload
    body_builder: Callable[[Any], Any] | None = None
    description: str = ""


@dataclass
class QuerySpec:
    fn: Any
    description: str = ""


@dataclass
class UpdateSpec:
    fn: Any
    body_model: type[BaseModel] | None = None
    body_builder: Callable[[Any], Any] | None = None
    description: str = ""


# ─── one workflow spec ─────────────────────────────────────────────
@dataclass
class WorkflowSpec:
    name: str  # URL slug, e.g. "controllable-batch"
    display_name: str  # Swagger tag label
    description: str
    workflow_class: Any
    run_method: Any  # workflow_class.run — used by start_workflow typed overload
    task_queue: str
    id_prefix: str
    start_body_model: type[BaseModel]
    # Convert Pydantic request → workflow input (dataclass/primitive/etc.)
    start_input_builder: Callable[[BaseModel], Any]
    signals: dict[str, SignalSpec] = field(default_factory=dict)
    queries: dict[str, QuerySpec] = field(default_factory=dict)
    updates: dict[str, UpdateSpec] = field(default_factory=dict)


# ─── helpers for input conversion ─────────────────────────────────
def _batch_input_builder(r: StartBatchRequest) -> ParentInput:
    return ParentInput(
        total_items=r.total_items,
        batch_size=r.batch_size,
        max_concurrent_children=r.concurrency,
        batches_per_run=r.batches_per_run,
    )


def _mcp_input_builder(r: StartMcpRequest) -> McpWorkflowInput:
    return McpWorkflowInput(
        tasks=[ToolInput(tool_name=t.tool_name, args=t.args) for t in r.tasks]
    )


# ─── the registry ─────────────────────────────────────────────────
WORKFLOWS: list[WorkflowSpec] = [
    WorkflowSpec(
        name="controllable-batch",
        display_name="Controllable Batch",
        description="Fan-out batch workflow with pause/resume/stop controls",
        workflow_class=ControllableBatchParentWorkflow,
        run_method=ControllableBatchParentWorkflow.run,
        task_queue=BATCH_QUEUE,
        id_prefix="ctl-batch",
        start_body_model=StartControllableBatchRequest,
        start_input_builder=_batch_input_builder,
        signals={
            "pause": SignalSpec(
                ControllableBatchParentWorkflow.request_pause,
                description="Pause at the next window boundary",
            ),
            "resume": SignalSpec(
                ControllableBatchParentWorkflow.request_resume,
                description="Clear the pause flag",
            ),
            "stop": SignalSpec(
                ControllableBatchParentWorkflow.request_stop,
                description="Graceful stop — finish in-flight, return summary",
            ),
        },
        queries={
            "state": QuerySpec(
                ControllableBatchParentWorkflow.state,
                description="running | paused | stopping",
            ),
            "progress": QuerySpec(
                ControllableBatchParentWorkflow.progress,
                description="State + offset + processed + failed",
            ),
        },
        updates={
            "pause-wait": UpdateSpec(
                ControllableBatchParentWorkflow.pause_and_wait,
                description="Pause and block until actually paused; returns snapshot",
            ),
        },
    ),
    WorkflowSpec(
        name="batch",
        display_name="Batch (plain)",
        description="Fan-out batch workflow without pause/resume",
        workflow_class=BatchParentWorkflow,
        run_method=BatchParentWorkflow.run,
        task_queue=BATCH_QUEUE,
        id_prefix="batch",
        start_body_model=StartBatchRequest,
        start_input_builder=_batch_input_builder,
        queries={
            "progress": QuerySpec(
                BatchParentWorkflow.progress,
                description="Offset + processed + failed",
            ),
        },
    ),
    WorkflowSpec(
        name="approval",
        display_name="Approval (human-in-the-loop)",
        description="Durable wait for a human approve/reject decision",
        workflow_class=ApprovalWorkflow,
        run_method=ApprovalWorkflow.run,
        task_queue=BATCH_QUEUE,
        id_prefix="approval",
        start_body_model=StartApprovalRequest,
        start_input_builder=lambda r: ApprovalRequest(**r.model_dump()),
        signals={
            "decide": SignalSpec(
                ApprovalWorkflow.decide,
                body_model=DecideRequest,
                body_builder=lambda r: ApprovalDecision(**r.model_dump()),
                description="Approve or reject",
            ),
        },
        queries={
            "state": QuerySpec(
                ApprovalWorkflow.get_state, description="Full state + history"
            ),
            "status": QuerySpec(
                ApprovalWorkflow.get_status,
                description="pending | approved | rejected | timed_out",
            ),
        },
        updates={
            "update-amount": UpdateSpec(
                ApprovalWorkflow.update_amount,
                body_model=UpdateAmountRequest,
                body_builder=lambda r: r.new_amount,
                description="Change requested amount while still pending",
            ),
        },
    ),
    WorkflowSpec(
        name="notify",
        display_name="Notify",
        description="Upload a report to SharePoint and email a link",
        workflow_class=NotifyWorkflow,
        run_method=NotifyWorkflow.run,
        task_queue=BATCH_QUEUE,
        id_prefix="notify",
        start_body_model=StartNotifyRequest,
        start_input_builder=lambda r: NotifyInput(**r.model_dump()),
    ),
    WorkflowSpec(
        name="mcp",
        display_name="MCP tool runner",
        description="Pin a worker-local MCP session, run tool calls",
        workflow_class=McpWorkflow,
        run_method=McpWorkflow.run,
        task_queue=MCP_SHARED_QUEUE,
        id_prefix="mcp",
        start_body_model=StartMcpRequest,
        start_input_builder=_mcp_input_builder,
    ),
]
