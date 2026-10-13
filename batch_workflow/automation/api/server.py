"""Custom Temporal UI — FastAPI backend that wraps Temporal SDK.

This is YOUR web app, not the official Temporal UI. You control every
endpoint, every permission check, and every UI element.

Run:
    uv run uvicorn automation.api.server:app --reload --port 8888

Then open http://localhost:8888/docs for interactive Swagger UI.

Temporal SDK capabilities used:
  - client.list_workflows()        → list/search workflows
  - client.start_workflow()        → start new workflow
  - handle.query()                 → read workflow state
  - handle.signal()                → send human decision
  - handle.execute_update()        → modify + get reply
  - handle.cancel() / .terminate() → stop workflow
  - handle.describe()              → execution metadata
  - handle.result()                → wait for completion
  - client.get_workflow_handle()   → get handle by ID
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from temporalio.client import Client, WorkflowExecutionStatus

from automation.config.queues import BATCH_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS

logger = logging.getLogger(__name__)

# ─── Temporal client (singleton, created at startup) ─────────────
_client: Client | None = None


async def get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(TEMPORAL_ADDRESS)
    return _client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to Temporal on startup."""
    global _client
    _client = await Client.connect(TEMPORAL_ADDRESS)
    logger.info("Connected to Temporal at %s", TEMPORAL_ADDRESS)
    yield
    _client = None


app = FastAPI(
    title="Temporal Custom UI",
    description="Custom dashboard & control panel for Temporal workflows",
    version="0.1.0",
    lifespan=lifespan,
)


# ═══════════════════════════════════════════════════════════════════
# 1. LIST / SEARCH WORKFLOWS
# ═══════════════════════════════════════════════════════════════════


@app.get("/api/workflows")
async def list_workflows(
    query: str = Query(
        default="",
        description=(
            "Temporal Visibility query (SQL-like). "
            "Examples: "
            "WorkflowType='ApprovalWorkflow', "
            "ExecutionStatus='Running', "
            "StartTime > '2026-01-01T00:00:00Z'"
        ),
    ),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List/search workflows using Temporal's Visibility API.

    This is the same query language the official Temporal UI uses.
    You can add custom Search Attributes for richer filtering.
    """
    client = await get_client()
    workflows = []

    async for wf in client.list_workflows(query=query or None, page_size=limit):
        workflows.append(
            {
                "workflow_id": wf.id,
                "run_id": wf.run_id,
                "type": wf.workflow_type,
                "status": wf.status.name if wf.status else "UNKNOWN",
                "start_time": wf.start_time.isoformat() if wf.start_time else None,
                "close_time": wf.close_time.isoformat() if wf.close_time else None,
                "task_queue": wf.task_queue,
            }
        )
        if len(workflows) >= limit:
            break

    return {"workflows": workflows, "count": len(workflows)}


# ═══════════════════════════════════════════════════════════════════
# 2. WORKFLOW DETAIL — describe + query
# ═══════════════════════════════════════════════════════════════════


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get workflow execution details (metadata + status)."""
    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)

    try:
        desc = await handle.describe()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "workflow_id": desc.id,
        "run_id": desc.run_id,
        "type": desc.workflow_type,
        "status": desc.status.name if desc.status else "UNKNOWN",
        "start_time": desc.start_time.isoformat() if desc.start_time else None,
        "close_time": desc.close_time.isoformat() if desc.close_time else None,
        "task_queue": desc.task_queue,
        "history_length": desc.history_length,
    }


@app.get("/api/workflows/{workflow_id}/query/{query_name}")
async def query_workflow(workflow_id: str, query_name: str):
    """Run a query on a workflow (read-only state inspection).

    Example: GET /api/workflows/approval-demo-001/query/get_state
    """
    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)

    try:
        result = await handle.query(query_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Convert dataclass → dict if needed
    if hasattr(result, "__dataclass_fields__"):
        result = asdict(result)

    return {"query": query_name, "result": result}


# ═══════════════════════════════════════════════════════════════════
# 3. START WORKFLOW
# ═══════════════════════════════════════════════════════════════════


class StartApprovalRequest(BaseModel):
    requester: str = "alice@example.com"
    approver: str = "bob-manager@example.com"
    request_type: str = "leave"
    description: str = "Annual leave request"
    amount: float = 0.0
    timeout_hours: int = 72


@app.post("/api/workflows/approval/start")
async def start_approval(req: StartApprovalRequest):
    """Start a new approval workflow."""
    from automation.models.approval import ApprovalRequest
    from automation.processes.approval.approval_workflow import ApprovalWorkflow

    client = await get_client()
    workflow_id = f"approval-{req.requester.split('@')[0]}-{req.request_type}"

    approval_input = ApprovalRequest(
        requester=req.requester,
        approver=req.approver,
        request_type=req.request_type,
        description=req.description,
        amount=req.amount,
        timeout_hours=req.timeout_hours,
    )

    try:
        handle = await client.start_workflow(
            ApprovalWorkflow.run,
            approval_input,
            id=workflow_id,
            task_queue=BATCH_QUEUE,
        )
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        "workflow_id": handle.id,
        "status": "started",
        "message": f"Waiting for {req.approver} to decide",
    }


# ═══════════════════════════════════════════════════════════════════
# 4. SIGNAL — send human decision (fire-and-forget)
# ═══════════════════════════════════════════════════════════════════


class DecisionRequest(BaseModel):
    approved: bool
    comment: str = ""
    decided_by: str = ""


@app.post("/api/workflows/{workflow_id}/decide")
async def send_decision(workflow_id: str, req: DecisionRequest):
    """Send an approval/rejection signal to the workflow.

    This is the core human-in-the-loop interaction:
    the human clicks a button on YOUR UI → this endpoint
    → Temporal signal → workflow wakes up and proceeds.
    """
    from automation.models.approval import ApprovalDecision
    from automation.processes.approval.approval_workflow import ApprovalWorkflow

    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)

    decision = ApprovalDecision(
        approved=req.approved,
        comment=req.comment,
        decided_by=req.decided_by,
    )

    try:
        await handle.signal(ApprovalWorkflow.decide, decision)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    action = "approved" if req.approved else "rejected"
    return {"workflow_id": workflow_id, "action": action}


# ═══════════════════════════════════════════════════════════════════
# 5. UPDATE — modify request + get synchronous reply
# ═══════════════════════════════════════════════════════════════════


class UpdateAmountRequest(BaseModel):
    new_amount: float


@app.post("/api/workflows/{workflow_id}/update-amount")
async def update_amount(workflow_id: str, req: UpdateAmountRequest):
    """Update the requested amount (synchronous — returns confirmation).

    Unlike signal (fire-and-forget), update waits for the workflow
    to validate and confirm the change.
    """
    from automation.processes.approval.approval_workflow import ApprovalWorkflow

    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)

    try:
        result = await handle.execute_update(
            ApprovalWorkflow.update_amount,
            req.new_amount,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"workflow_id": workflow_id, "result": result}


# ═══════════════════════════════════════════════════════════════════
# 6. CANCEL / TERMINATE
# ═══════════════════════════════════════════════════════════════════


@app.post("/api/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str):
    """Request graceful cancellation (workflow can run cleanup logic)."""
    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.cancel()
    return {"workflow_id": workflow_id, "action": "cancel_requested"}


@app.post("/api/workflows/{workflow_id}/terminate")
async def terminate_workflow(workflow_id: str, reason: str = ""):
    """Force terminate (no cleanup, immediate stop)."""
    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.terminate(reason or "Terminated via custom UI")
    return {"workflow_id": workflow_id, "action": "terminated"}


# ═══════════════════════════════════════════════════════════════════
# 7. DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════════


@app.get("/api/dashboard/stats")
async def dashboard_stats():
    """Aggregate statistics for a dashboard view."""
    client = await get_client()

    async def count_query(q: str) -> int:
        n = 0
        async for _ in client.list_workflows(query=q, page_size=1):
            n += 1
            if n > 999:
                break
        return n

    running = await count_query('ExecutionStatus="Running"')
    completed = await count_query('ExecutionStatus="Completed"')
    failed = await count_query('ExecutionStatus="Failed"')
    timed_out = await count_query('ExecutionStatus="TimedOut"')

    # Pending approvals
    pending_approvals = await count_query(
        "WorkflowType='ApprovalWorkflow' AND ExecutionStatus='Running'"
    )

    return {
        "running": running,
        "completed": completed,
        "failed": failed,
        "timed_out": timed_out,
        "pending_approvals": pending_approvals,
    }
