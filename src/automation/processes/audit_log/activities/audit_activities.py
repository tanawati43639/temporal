from __future__ import annotations

from datetime import datetime, timedelta, timezone

import json

from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowExecutionStatus

from config.settings import TEMPORAL_ADDRESS, get_tls_config

from ..configs.queues import MAX_WORKFLOWS_PER_NAMESPACE
from ..models.audit import AuditEntry, ScanNamespaceInput

_STATUS_NAMES: dict[int, str] = {
    WorkflowExecutionStatus.RUNNING: "running",
    WorkflowExecutionStatus.COMPLETED: "completed",
    WorkflowExecutionStatus.FAILED: "failed",
    WorkflowExecutionStatus.CANCELED: "canceled",
    WorkflowExecutionStatus.TERMINATED: "terminated",
    WorkflowExecutionStatus.CONTINUED_AS_NEW: "continued_as_new",
    WorkflowExecutionStatus.TIMED_OUT: "timed_out",
}

_IDENTITY_EVENTS: dict[int, str] = {
    EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED: "started",
    EventType.EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED: "signaled",
    EventType.EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED: "terminated",
    EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED: "cancel_requested",
}


def _extract_identity(event) -> str | None:
    """Pull the identity string from a history event's typed attributes."""
    et = event.event_type
    if et == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED:
        return event.workflow_execution_started_event_attributes.identity
    if et == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED:
        return event.workflow_execution_signaled_event_attributes.identity
    if et == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED:
        return event.workflow_execution_terminated_event_attributes.identity
    if et == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED:
        attrs = event.request_cancel_external_workflow_execution_initiated_event_attributes
        return getattr(attrs, "identity", None) if attrs else None
    return None


@activity.defn
async def scan_namespace_audit(input: ScanNamespaceInput) -> list[AuditEntry]:
    """List workflows in a namespace and extract identity from key events."""
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=input.namespace, tls=get_tls_config()
    )
    if input.lookback_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=input.lookback_days)
        query = f"StartTime > '{cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}'"
    else:
        query = ""

    entries: list[AuditEntry] = []
    scanned = 0

    async for wf_exec in client.list_workflows(query=query):
        if scanned >= MAX_WORKFLOWS_PER_NAMESPACE:
            break

        status = _STATUS_NAMES.get(wf_exec.status, str(wf_exec.status))
        start_iso = wf_exec.start_time.isoformat() if wf_exec.start_time else ""
        close_iso = wf_exec.close_time.isoformat() if wf_exec.close_time else ""
        duration_ms = 0
        if wf_exec.start_time and wf_exec.close_time:
            duration_ms = int((wf_exec.close_time - wf_exec.start_time).total_seconds() * 1000)
        parent_wf_id = wf_exec.parent_id or ""
        sa = {k: json.dumps(v) for k, v in (wf_exec.search_attributes or {}).items()}

        handle = client.get_workflow_handle(wf_exec.id, run_id=wf_exec.run_id)
        try:
            async for event in handle.fetch_history_events():
                if event.event_type not in _IDENTITY_EVENTS:
                    continue
                identity = _extract_identity(event)
                label = _IDENTITY_EVENTS[event.event_type]
                entries.append(
                    AuditEntry(
                        workflow_id=wf_exec.id,
                        run_id=wf_exec.run_id or "",
                        workflow_type=wf_exec.workflow_type or "",
                        namespace=input.namespace,
                        event_type=label,
                        identity=identity or "",
                        timestamp=event.event_time.ToDatetime().isoformat()
                        if event.event_time
                        else "",
                        status=status,
                        task_queue=wf_exec.task_queue or "",
                        start_time=start_iso,
                        close_time=close_iso,
                        execution_duration_ms=duration_ms,
                        parent_workflow_id=parent_wf_id,
                        search_attributes=sa,
                    )
                )
        except Exception as exc:
            activity.logger.warning(
                "Failed to read history for %s/%s: %s",
                wf_exec.id,
                wf_exec.run_id,
                exc,
            )

        scanned += 1
        if scanned % 10 == 0:
            activity.heartbeat(f"{input.namespace}: scanned {scanned} workflows")

    activity.heartbeat(f"{input.namespace}: done — {scanned} workflows, {len(entries)} entries")
    return entries


ACTIVITIES = [scan_namespace_audit]
