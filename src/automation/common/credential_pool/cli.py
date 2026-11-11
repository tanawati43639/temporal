"""CLI for managing credential pools.

Run:
    # Start a pool with 3 SAP credentials
    uv run python -m automation.common.credential_pool.cli start \
        --pool SAP_POOL --credentials SAP_01 SAP_02 SAP_03

    # Check pool status
    uv run python -m automation.common.credential_pool.cli status --pool SAP_POOL

    # Force release a credential (admin)
    uv run python -m automation.common.credential_pool.cli release \
        --pool SAP_POOL --credential SAP_01 --holder some-workflow-id-acquire

    # Shut down a pool
    uv run python -m automation.common.credential_pool.cli shutdown --pool SAP_POOL
"""

import argparse
import asyncio

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config, temporal_ui_link

from .configs.pool_config import CREDENTIAL_POOL_QUEUE, LOCK_TIMEOUT_SECONDS
from .models.pool import PoolConfig, ReleaseSignal
from .workflows.pool_manager import CredentialPoolWorkflow


async def cmd_start(args) -> None:
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    workflow_id = f"cred-pool-{args.pool}"
    handle = await client.start_workflow(
        CredentialPoolWorkflow.run,
        PoolConfig(
            pool_name=args.pool,
            credential_names=args.credentials,
            lock_timeout_seconds=args.timeout,
        ),
        id=workflow_id,
        task_queue=CREDENTIAL_POOL_QUEUE,
    )
    print(f"Pool started: {handle.id}")
    print(f"Credentials: {args.credentials}")
    print(f"UI: {temporal_ui_link(handle.id)}")


async def cmd_status(args) -> None:
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    handle = client.get_workflow_handle(f"cred-pool-{args.pool}")
    result = await handle.query("status")

    print(f"Pool: {result.pool_name}")
    print(f"Stats: {result.total_acquires} acquires, {result.total_releases} releases")
    print(f"Queue: {result.queue or '(empty)'}")
    print("Credentials:")
    for entry in result.credentials:
        if entry.is_locked:
            print(f"  {entry.credential_name:20s} LOCKED  by {entry.holder_workflow_id}  since {entry.acquired_at}")
        else:
            print(f"  {entry.credential_name:20s} FREE")


async def cmd_release(args) -> None:
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    handle = client.get_workflow_handle(f"cred-pool-{args.pool}")
    await handle.signal(
        "release",
        ReleaseSignal(
            requester_workflow_id=args.holder,
            credential_name=args.credential,
        ),
    )
    print(f"Force-released '{args.credential}' from {args.holder}")


async def cmd_shutdown(args) -> None:
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    handle = client.get_workflow_handle(f"cred-pool-{args.pool}")
    await handle.signal("shutdown")
    print(f"Shutdown signal sent to cred-pool-{args.pool}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Credential Pool CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Start a credential pool")
    p_start.add_argument("--pool", required=True, help="Pool name")
    p_start.add_argument("--credentials", nargs="+", required=True, help="Credential names in the pool")
    p_start.add_argument("--timeout", type=int, default=LOCK_TIMEOUT_SECONDS, help="Lock timeout seconds")

    p_status = sub.add_parser("status", help="Show pool status")
    p_status.add_argument("--pool", required=True, help="Pool name")

    p_release = sub.add_parser("release", help="Force-release a credential (admin)")
    p_release.add_argument("--pool", required=True, help="Pool name")
    p_release.add_argument("--credential", required=True, help="Credential name to release")
    p_release.add_argument("--holder", required=True, help="Current holder workflow ID")

    p_shutdown = sub.add_parser("shutdown", help="Shut down a pool")
    p_shutdown.add_argument("--pool", required=True, help="Pool name")

    return parser


async def main() -> None:
    args = build_parser().parse_args()
    dispatch = {
        "start": cmd_start,
        "status": cmd_status,
        "release": cmd_release,
        "shutdown": cmd_shutdown,
    }
    await dispatch[args.command](args)


if __name__ == "__main__":
    asyncio.run(main())
