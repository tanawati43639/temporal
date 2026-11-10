"""Start an AuditLogWorkflow from the CLI.

Run:
    uv run python -m automation.processes.audit_log.clients.starter --days 7
    uv run python -m automation.processes.audit_log.clients.starter --days 30 --ns default --ns dev
"""

import argparse
import asyncio
import uuid

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config, temporal_ui_link

from ..configs.queues import AUDIT_LOG_QUEUE
from ..models.audit import AuditInput
from ..workflows.audit_log import AuditLogWorkflow


async def main() -> None:
    parser = argparse.ArgumentParser(description="Start an audit-log workflow")
    parser.add_argument("--days", type=int, required=True, help="Lookback days")
    parser.add_argument("--ns", action="append", help="Namespace(s) to scan (repeatable)")
    parser.add_argument("--wait-result", action="store_true", help="Block until done")
    args = parser.parse_args()

    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )

    workflow_id = f"audit-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        AuditLogWorkflow.run,
        AuditInput(
            lookback_days=args.days,
            namespace_filter=args.ns,
        ),
        id=workflow_id,
        task_queue=AUDIT_LOG_QUEUE,
    )
    print(f"Started workflow: {handle.id}")
    print(f"UI: {temporal_ui_link(handle.id)}")

    if args.wait_result:
        result = await handle.result()
        print(f"\nAudit complete — {result.total_entries} entries across {result.namespaces_scanned}")
        for entry in result.entries:
            print(f"  [{entry.namespace}] {entry.event_type:20s} {entry.identity:30s} {entry.workflow_id}")


if __name__ == "__main__":
    asyncio.run(main())
