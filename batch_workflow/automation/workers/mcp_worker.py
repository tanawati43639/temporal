"""MCP worker — listens on two task queues:

1. Shared queue  → receives acquire_mcp_session (any worker can pick up)
2. Worker-specific queue → receives call_mcp_tool + release_mcp_session
                           (pinned to this worker after acquire)

Run:  python -m automation.workers.mcp_worker
      python -m automation.workers.mcp_worker --identity vm-1 --mcp-cmd "python mcp_server.py"
"""

import argparse
import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from automation.config.queues import MCP_SHARED_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.objects.mcp.activities import (
    acquire_mcp_session,
    call_mcp_tool,
    init_session_manager,
    release_mcp_session,
)
from automation.processes.mcp.mcp_workflow import McpWorkflow
from automation.workers.mcp_session import WORKER_MCP_QUEUE, McpSessionManager


async def run_worker(
    identity: str = "mcp-worker-1",
    mcp_command: list[str] | None = None,
    idle_timeout: float = 300.0,
) -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    client = await Client.connect(TEMPORAL_ADDRESS, identity=identity)

    # McpSessionManager — ดูแล lifecycle ของ MCP server บน worker นี้
    session_mgr = McpSessionManager(
        command=mcp_command or ["python", "mcp_server.py"],
        idle_timeout=idle_timeout,
    )
    init_session_manager(session_mgr)

    # Worker 1: shared queue — รับ acquire + workflow
    shared_worker = Worker(
        client,
        task_queue=MCP_SHARED_QUEUE,
        workflows=[McpWorkflow],
        activities=[acquire_mcp_session],
    )

    # Worker 2: worker-specific queue — รับ call_mcp_tool + release
    pinned_worker = Worker(
        client,
        task_queue=WORKER_MCP_QUEUE,
        activities=[call_mcp_tool, release_mcp_session],
    )

    logger.info(
        "MCP Worker '%s' started\n"
        "  shared queue : %s (acquire + workflows)\n"
        "  pinned queue : %s (call_mcp_tool + release)\n"
        "  idle timeout : %.0fs",
        identity,
        MCP_SHARED_QUEUE,
        WORKER_MCP_QUEUE,
        idle_timeout,
    )

    # รัน 2 worker พร้อมกัน — ทั้งคู่หยุดเมื่อ shutdown
    async with shared_worker, pinned_worker:
        shutdown = asyncio.Event()
        try:
            await shutdown.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await session_mgr.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an MCP Temporal worker")
    parser.add_argument("--identity", default="mcp-worker-1")
    parser.add_argument("--mcp-cmd", default="python mcp_server.py", help="command to start MCP server")
    parser.add_argument("--idle-timeout", type=float, default=300.0, help="MCP idle auto-stop (seconds)")
    args = parser.parse_args()

    asyncio.run(
        run_worker(
            identity=args.identity,
            mcp_command=args.mcp_cmd.split(),
            idle_timeout=args.idle_timeout,
        )
    )


if __name__ == "__main__":
    main()
