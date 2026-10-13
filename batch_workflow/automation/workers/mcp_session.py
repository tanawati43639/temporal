"""MCP server lifecycle manager — starts, monitors, and stops the local
MCP server subprocess.  Lives entirely on the worker side; workflows
never import or interact with this module.

The idle watchdog automatically terminates an MCP server that has not
been touched by any activity for *idle_timeout* seconds, preventing
resource leaks after workflow resets or cancellations.
"""

import asyncio
import logging
import socket
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

WORKER_MCP_QUEUE = f"mcp-{socket.gethostname()}"


@dataclass
class McpSessionManager:
    command: list[str] = field(default_factory=lambda: ["python", "mcp_server.py"])
    idle_timeout: float = 300.0  # 5 minutes
    startup_timeout: float = 45.0
    health_url: str = "http://localhost:3000/health"

    _process: subprocess.Popen | None = field(default=None, init=False, repr=False)
    _last_used: float = field(default=0.0, init=False, repr=False)
    _watchdog_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    # ── public API ──────────────────────────────────────────────

    async def acquire(self) -> str:
        """Start MCP server if not running. Returns the worker-specific
        task queue name so the workflow can pin subsequent activities."""
        async with self._lock:
            if not self._is_alive():
                logger.info("Starting MCP server: %s", self.command)
                self._process = subprocess.Popen(
                    self.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                await self._wait_until_ready()
                logger.info("MCP server ready (pid=%d)", self._process.pid)

            self._touch()

            if self._watchdog_task is None or self._watchdog_task.done():
                self._watchdog_task = asyncio.create_task(self._idle_watchdog())

        return WORKER_MCP_QUEUE

    def touch(self) -> None:
        """Reset the idle timer — called by every MCP activity."""
        self._touch()

    async def release(self) -> None:
        """Explicitly stop the MCP server (called from release activity)."""
        async with self._lock:
            await self._stop("explicit release")

    @property
    def is_alive(self) -> bool:
        return self._is_alive()

    # ── internal ────────────────────────────────────────────────

    def _touch(self) -> None:
        self._last_used = time.monotonic()

    def _is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    async def _wait_until_ready(self) -> None:
        """Poll the health endpoint until the MCP server is responsive."""
        import aiohttp

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.health_url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            return
            except (aiohttp.ClientError, OSError):
                pass
            await asyncio.sleep(1)
        raise RuntimeError(
            f"MCP server did not become ready within {self.startup_timeout}s"
        )

    async def _stop(self, reason: str) -> None:
        if self._is_alive():
            logger.info("Stopping MCP server (pid=%d, reason=%s)", self._process.pid, reason)
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            logger.info("MCP server stopped")
        self._process = None

        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None

    async def _idle_watchdog(self) -> None:
        """Background task: auto-stop MCP server after idle_timeout."""
        logger.info("Idle watchdog started (timeout=%.0fs)", self.idle_timeout)
        try:
            while self._is_alive():
                await asyncio.sleep(30)
                idle_secs = time.monotonic() - self._last_used
                if idle_secs > self.idle_timeout:
                    async with self._lock:
                        if time.monotonic() - self._last_used > self.idle_timeout:
                            await self._stop(f"idle {idle_secs:.0f}s")
                            return
        except asyncio.CancelledError:
            pass
        logger.info("Idle watchdog exited")
