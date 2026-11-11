"""Control a running CredentialLockWorkflow.

Run:
    uv run python -m automation.processes.credential_lock.clients.control \
        --credential SAP_01 --action status

    uv run python -m automation.processes.credential_lock.clients.control \
        --credential SAP_01 --action acquire --requester my-workflow-123

    uv run python -m automation.processes.credential_lock.clients.control \
        --credential SAP_01 --action release --requester my-workflow-123

    uv run python -m automation.processes.credential_lock.clients.control \
        --credential SAP_01 --action shutdown
"""

import argparse
import asyncio

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config

from ..models.credential import AcquireRequest, ReleaseRequest


async def main() -> None:
    parser = argparse.ArgumentParser(description="Control a credential lock")
    parser.add_argument("--credential", required=True, help="Credential name")
    parser.add_argument(
        "--action",
        required=True,
        choices=["status", "acquire", "release", "shutdown"],
        help="Action to perform",
    )
    parser.add_argument("--requester", help="Requester workflow ID (for acquire/release)")
    parser.add_argument("--timeout", type=int, default=300, help="Lock timeout (for acquire)")
    args = parser.parse_args()

    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )

    workflow_id = f"cred-lock-{args.credential}"
    handle = client.get_workflow_handle(workflow_id)

    if args.action == "status":
        result = await handle.query("status")
        print(f"Credential: {result.credential_name}")
        if result.holder:
            print(f"Holder:     {result.holder.workflow_id} (since {result.holder.acquired_at})")
        else:
            print("Holder:     (none — lock is free)")
        print(f"Queue:      {result.queue or '(empty)'}")
        print(f"Stats:      {result.total_acquires} acquires, {result.total_releases} releases")

    elif args.action == "acquire":
        if not args.requester:
            parser.error("--requester is required for acquire")
        await handle.signal(
            "acquire",
            AcquireRequest(
                requester_workflow_id=args.requester,
                credential_name=args.credential,
                timeout_seconds=args.timeout,
            ),
        )
        print(f"Acquire request sent for '{args.credential}' by {args.requester}")

    elif args.action == "release":
        if not args.requester:
            parser.error("--requester is required for release")
        await handle.signal(
            "release",
            ReleaseRequest(requester_workflow_id=args.requester),
        )
        print(f"Release sent for '{args.credential}' by {args.requester}")

    elif args.action == "shutdown":
        await handle.signal("shutdown")
        print(f"Shutdown signal sent to {workflow_id}")


if __name__ == "__main__":
    asyncio.run(main())
