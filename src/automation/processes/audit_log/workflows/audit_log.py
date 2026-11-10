from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from automation.processes.audit_log.activities.audit_activities import (
        scan_namespace_audit,
    )
    from automation.processes.audit_log.models.audit import (
        AuditEntry,
        AuditInput,
        AuditResult,
        ScanNamespaceInput,
    )

DEFAULT_NAMESPACES = ["default"]


@workflow.defn
class AuditLogWorkflow:

    def __init__(self) -> None:
        self._scanned: list[str] = []
        self._total_entries = 0

    @workflow.query
    def progress(self) -> dict:
        return {
            "namespaces_done": list(self._scanned),
            "total_entries": self._total_entries,
        }

    @workflow.run
    async def run(self, input: AuditInput) -> AuditResult:
        namespaces = input.namespace_filter or DEFAULT_NAMESPACES
        all_entries: list[AuditEntry] = []

        for ns in namespaces:
            entries: list[AuditEntry] = await workflow.execute_activity(
                scan_namespace_audit,
                ScanNamespaceInput(namespace=ns, lookback_days=input.lookback_days),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
            )
            all_entries.extend(entries)
            self._scanned.append(ns)
            self._total_entries = len(all_entries)

        return AuditResult(
            total_entries=len(all_entries),
            namespaces_scanned=list(namespaces),
            entries=all_entries,
        )
