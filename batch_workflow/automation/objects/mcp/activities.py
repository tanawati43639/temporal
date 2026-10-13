"""MCP session activities — acquire, call tool, release.

These activities run on the worker side and use McpSessionManager
to control the local MCP server lifecycle.
"""

import logging

from temporalio import activity

from automation.objects.mcp.models import SessionInfo, ToolInput, ToolOutput
from automation.workers.mcp_session import McpSessionManager

logger = logging.getLogger(__name__)

# Singleton per worker process — initialized in worker setup
_session_mgr: McpSessionManager | None = None


def init_session_manager(mgr: McpSessionManager) -> None:
    global _session_mgr
    _session_mgr = mgr


def _mgr() -> McpSessionManager:
    if _session_mgr is None:
        raise RuntimeError("McpSessionManager not initialized — call init_session_manager() at worker startup")
    return _session_mgr


@activity.defn
async def acquire_mcp_session() -> SessionInfo:
    """Start MCP server on this worker and return the worker-specific
    task queue so the workflow can pin remaining activities here."""
    mgr = _mgr()
    task_queue = await mgr.acquire()
    logger.info("Session acquired on queue: %s", task_queue)
    return SessionInfo(task_queue=task_queue)


@activity.defn
async def call_mcp_tool(input: ToolInput) -> ToolOutput:
    """Call a tool on the local MCP server.  Resets the idle timer."""
    mgr = _mgr()

    if not mgr.is_alive:
        raise activity.ApplicationError(
            "MCP server not available on this worker",
            non_retryable=False,
        )

    mgr.touch()

    # ── เรียก MCP server จริง ──
    # แก้ตรงนี้ให้ตรงกับ MCP client ที่ใช้จริง
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:3000/call",
            json={"tool": input.tool_name, "args": input.args},
            timeout=aiohttp.ClientTimeout(total=55),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

    return ToolOutput(result=data)


@activity.defn
async def release_mcp_session() -> None:
    """Stop the MCP server on this worker."""
    mgr = _mgr()
    await mgr.release()
    logger.info("Session released")
