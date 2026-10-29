"""Endpoint factory — turns one WorkflowSpec into a full set of REST routes.

For each spec the factory mounts:
    POST /api/{name}/start                 - typed Pydantic body
    GET  /api/{name}                       - list workflows of this type
    GET  /api/{name}/{id}/describe         - execution metadata
    GET  /api/{name}/{id}/status           - run every declared query
    POST /api/{name}/{id}/signals/{name}   - one per declared signal
    POST /api/{name}/{id}/updates/{name}   - one per declared update
    POST /api/{name}/{id}/cancel           - every workflow gets this
    POST /api/{name}/{id}/terminate        - every workflow gets this

Dynamic registration relies on Python evaluating function annotations at
def-time (so NO ``from __future__ import annotations`` here): FastAPI inspects
the resulting signature to build the Swagger schema.
"""

import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from config.settings import temporal_ui_link

from .client import get_client
from .spec import SignalSpec, UpdateSpec, WorkflowSpec


def _to_jsonable(value: Any) -> Any:
    """Convert dataclasses to dicts so FastAPI can serialize them."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def _mount_signal(app: FastAPI, base: str, tag: str, name: str, sspec: SignalSpec):
    """Mount POST /{base}/{wid}/signals/{name}."""
    path = f"{base}/{{wid}}/signals/{name}"
    description = sspec.description or f"Send '{name}' signal"

    if sspec.body_model is None:
        async def send_signal(wid: str):
            client = await get_client()
            try:
                await client.get_workflow_handle(wid).signal(sspec.fn)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"workflow_id": wid, "signal": name, "status": "sent"}
    else:
        body_model = sspec.body_model  # pin into closure

        async def send_signal(wid: str, req: body_model):  # type: ignore[valid-type]
            client = await get_client()
            arg = sspec.body_builder(req) if sspec.body_builder else req
            try:
                await client.get_workflow_handle(wid).signal(sspec.fn, arg)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"workflow_id": wid, "signal": name, "status": "sent"}

    send_signal.__name__ = f"signal_{tag}_{name}".replace("-", "_").replace(" ", "_")
    send_signal.__doc__ = description
    app.post(path, tags=[tag], summary=description)(send_signal)


def _mount_update(app: FastAPI, base: str, tag: str, name: str, uspec: UpdateSpec):
    """Mount POST /{base}/{wid}/updates/{name} (synchronous)."""
    path = f"{base}/{{wid}}/updates/{name}"
    description = uspec.description or f"Execute '{name}' update"

    if uspec.body_model is None:
        async def send_update(wid: str):
            client = await get_client()
            try:
                result = await client.get_workflow_handle(wid).execute_update(uspec.fn)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"workflow_id": wid, "update": name, "result": _to_jsonable(result)}
    else:
        body_model = uspec.body_model

        async def send_update(wid: str, req: body_model):  # type: ignore[valid-type]
            client = await get_client()
            arg = uspec.body_builder(req) if uspec.body_builder else req
            try:
                result = await client.get_workflow_handle(wid).execute_update(
                    uspec.fn, arg
                )
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"workflow_id": wid, "update": name, "result": _to_jsonable(result)}

    send_update.__name__ = f"update_{tag}_{name}".replace("-", "_").replace(" ", "_")
    send_update.__doc__ = description
    app.post(path, tags=[tag], summary=description)(send_update)


def register_workflow_endpoints(app: FastAPI, spec: WorkflowSpec) -> None:
    """Mount the full endpoint set for one workflow spec."""
    tag = spec.display_name
    base = f"/api/{spec.name}"
    start_body_model = spec.start_body_model

    async def start(req: start_body_model):  # type: ignore[valid-type]
        client = await get_client()
        workflow_id = f"{spec.id_prefix}-{uuid.uuid4().hex[:8]}"
        try:
            handle = await client.start_workflow(
                spec.run_method,
                spec.start_input_builder(req),
                id=workflow_id,
                task_queue=spec.task_queue,
            )
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {
            "workflow_id": handle.id,
            "status": "started",
            "temporal_ui": temporal_ui_link(handle.id),
        }

    start.__name__ = f"start_{spec.name}".replace("-", "_")
    start.__doc__ = f"Start a new {spec.display_name} workflow"
    app.post(f"{base}/start", tags=[tag], summary=f"Start {spec.display_name}")(start)

    async def list_wf(limit: int = Query(default=20, ge=1, le=100)):
        client = await get_client()
        type_name = spec.workflow_class.__name__
        rows = []
        async for wf in client.list_workflows(
            query=f'WorkflowType="{type_name}"', page_size=limit
        ):
            rows.append(
                {
                    "workflow_id": wf.id,
                    "run_id": wf.run_id,
                    "status": wf.status.name if wf.status else "UNKNOWN",
                    "start_time": wf.start_time.isoformat() if wf.start_time else None,
                    "close_time": wf.close_time.isoformat() if wf.close_time else None,
                }
            )
            if len(rows) >= limit:
                break
        return {"workflows": rows, "count": len(rows)}

    list_wf.__name__ = f"list_{spec.name}".replace("-", "_")
    list_wf.__doc__ = f"List recent {spec.display_name} workflows"
    app.get(base, tags=[tag], summary=f"List {spec.display_name}")(list_wf)

    async def describe_wf(wid: str):
        client = await get_client()
        try:
            desc = await client.get_workflow_handle(wid).describe()
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {
            "workflow_id": desc.id,
            "run_id": desc.run_id,
            "type": desc.workflow_type,
            "status": desc.status.name if desc.status else "UNKNOWN",
            "task_queue": desc.task_queue,
            "history_length": desc.history_length,
            "start_time": desc.start_time.isoformat() if desc.start_time else None,
            "close_time": desc.close_time.isoformat() if desc.close_time else None,
        }

    describe_wf.__name__ = f"describe_{spec.name}".replace("-", "_")
    app.get(f"{base}/{{wid}}/describe", tags=[tag], summary="Describe execution")(
        describe_wf
    )

    if spec.queries:
        query_items = list(spec.queries.items())  # pin for closure

        async def status(wid: str):
            client = await get_client()
            handle = client.get_workflow_handle(wid)
            out: dict[str, Any] = {}
            for qname, qspec in query_items:
                try:
                    out[qname] = _to_jsonable(await handle.query(qspec.fn))
                except Exception as e:
                    out[qname] = {"_error": str(e)}
            return {"workflow_id": wid, "queries": out}

        status.__name__ = f"status_{spec.name}".replace("-", "_")
        status.__doc__ = (
            f"Run all queries: {', '.join(spec.queries)} — read-only snapshot"
        )
        app.get(
            f"{base}/{{wid}}/status",
            tags=[tag],
            summary=f"Status ({', '.join(spec.queries)})",
        )(status)

    for signal_name, sspec in spec.signals.items():
        _mount_signal(app, base, tag, signal_name, sspec)

    for update_name, uspec in spec.updates.items():
        _mount_update(app, base, tag, update_name, uspec)

    async def cancel_wf(wid: str):
        client = await get_client()
        try:
            await client.get_workflow_handle(wid).cancel()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"workflow_id": wid, "action": "cancel_requested"}

    cancel_wf.__name__ = f"cancel_{spec.name}".replace("-", "_")
    cancel_wf.__doc__ = "Request graceful cancellation (workflow runs cleanup)"
    app.post(f"{base}/{{wid}}/cancel", tags=[tag], summary="Cancel")(cancel_wf)

    async def terminate_wf(wid: str, reason: str = ""):
        client = await get_client()
        try:
            await client.get_workflow_handle(wid).terminate(
                reason or "Terminated via custom UI"
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"workflow_id": wid, "action": "terminated", "reason": reason}

    terminate_wf.__name__ = f"terminate_{spec.name}".replace("-", "_")
    terminate_wf.__doc__ = "Force-terminate (no cleanup)"
    app.post(f"{base}/{{wid}}/terminate", tags=[tag], summary="Terminate")(terminate_wf)
