"""Custom Temporal UI — FastAPI app assembled from the auto-discovered registry.

How to extend:
  - Add a new process package under automation/processes/ with a register.py
    that exports SPECS. Endpoints + Swagger forms appear on reload.

Global endpoints (not per-workflow):
  - GET /api/workflows               - raw Visibility search across all types
  - GET /api/workflows/{id}/history  - event history for any workflow
  - GET /api/dashboard/stats         - cluster-wide counts
  - GET /api/registry                - introspection: which workflows + routes

Run:
    uv run --extra web uvicorn automation.api.server:app --reload --port 8888
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from .client import get_client, lifespan
from .factory import register_workflow_endpoints
from .registry import WORKFLOWS

app = FastAPI(
    title="Temporal Custom UI",
    description=(
        "Auto-generated endpoints for every workflow a process registers in its "
        "`register.py`. Add a process and Swagger picks it up on reload."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


for _spec in WORKFLOWS:
    register_workflow_endpoints(app, _spec)


@app.get("/api/workflows", tags=["global"])
async def list_all_workflows(
    query: str = Query(
        default="",
        description=(
            "Temporal Visibility query. Examples: "
            'WorkflowType="ControllableBatchParentWorkflow", '
            'ExecutionStatus="Running"'
        ),
    ),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List workflows across all types using Visibility."""
    client = await get_client()
    rows = []
    async for wf in client.list_workflows(query=query or None, page_size=limit):
        rows.append(
            {
                "workflow_id": wf.id,
                "run_id": wf.run_id,
                "type": wf.workflow_type,
                "status": wf.status.name if wf.status else "UNKNOWN",
                "task_queue": wf.task_queue,
                "start_time": wf.start_time.isoformat() if wf.start_time else None,
                "close_time": wf.close_time.isoformat() if wf.close_time else None,
            }
        )
        if len(rows) >= limit:
            break
    return {"workflows": rows, "count": len(rows)}


@app.get("/api/workflows/{workflow_id}/history", tags=["global"])
async def workflow_history(
    workflow_id: str, limit: int = Query(default=100, ge=1, le=1000)
):
    """Return a compact view of the first `limit` events in history."""
    client = await get_client()
    try:
        handle = client.get_workflow_handle(workflow_id)
        events = []
        async for event in handle.fetch_history_events():
            events.append(
                {
                    "event_id": event.event_id,
                    "event_time": event.event_time.ToDatetime().isoformat()
                    if event.event_time
                    else None,
                    "event_type": event.event_type.__class__.__name__
                    if hasattr(event.event_type, "__class__")
                    else str(event.event_type),
                }
            )
            if len(events) >= limit:
                break
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"workflow_id": workflow_id, "events": events, "count": len(events)}


@app.get("/api/dashboard/stats", tags=["global"])
async def dashboard_stats():
    """Cluster-wide execution counts by status + per registered type."""
    client = await get_client()

    async def count_query(q: str) -> int:
        n = 0
        async for _ in client.list_workflows(query=q, page_size=1):
            n += 1
            if n > 999:
                break
        return n

    by_status = {
        "running": await count_query('ExecutionStatus="Running"'),
        "completed": await count_query('ExecutionStatus="Completed"'),
        "failed": await count_query('ExecutionStatus="Failed"'),
        "timed_out": await count_query('ExecutionStatus="TimedOut"'),
        "canceled": await count_query('ExecutionStatus="Canceled"'),
        "terminated": await count_query('ExecutionStatus="Terminated"'),
    }
    by_type = {
        spec.name: await count_query(
            f'WorkflowType="{spec.workflow_class.__name__}" '
            'AND ExecutionStatus="Running"'
        )
        for spec in WORKFLOWS
    }
    return {"by_status": by_status, "running_by_type": by_type}


@app.get("/api/registry", tags=["global"])
async def list_registered_workflows():
    """Enumerate every workflow + the routes mounted for it (for debugging)."""
    return [
        {
            "name": spec.name,
            "display_name": spec.display_name,
            "description": spec.description,
            "workflow_type": spec.workflow_class.__name__,
            "task_queue": spec.task_queue,
            "id_prefix": spec.id_prefix,
            "signals": list(spec.signals),
            "queries": list(spec.queries),
            "updates": list(spec.updates),
            "routes": [
                f"POST /api/{spec.name}/start",
                f"GET  /api/{spec.name}",
                f"GET  /api/{spec.name}/{{wid}}/describe",
                *([f"GET  /api/{spec.name}/{{wid}}/status"] if spec.queries else []),
                *[f"POST /api/{spec.name}/{{wid}}/signals/{s}" for s in spec.signals],
                *[f"POST /api/{spec.name}/{{wid}}/updates/{u}" for u in spec.updates],
                f"POST /api/{spec.name}/{{wid}}/cancel",
                f"POST /api/{spec.name}/{{wid}}/terminate",
            ],
        }
        for spec in WORKFLOWS
    ]
