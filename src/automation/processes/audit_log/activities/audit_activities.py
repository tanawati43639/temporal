from __future__ import annotations

from datetime import datetime, timedelta, timezone

from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, get_tls_config

from ..configs.queues import MAX_WORKFLOWS_PER_NAMESPACE
from ..models.audit import AuditEntry, ScanNamespaceInput

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
    cutoff = datetime.now(timezone.utc) - timedelta(days=input.lookback_days)
    query = f"StartTime > '{cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}'"

    entries: list[AuditEntry] = []
    scanned = 0

    async for wf_exec in client.list_workflows(query=query):
        if scanned >= MAX_WORKFLOWS_PER_NAMESPACE:
            break

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
                        timestamp=event.event_time.isoformat()
                        if event.event_time
                        else "",
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
