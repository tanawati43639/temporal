"""MCP process manager — lazy start + idle watchdog

ทั้งหมดอยู่ฝั่ง worker:
  - activity เรียก ensure_running() → start ถ้ายังไม่รัน
  - idle watchdog → stop อัตโนมัติหลังไม่มีงาน 5 นาที
"""

import asyncio
import logging
import subprocess
import threading
import time

import aiohttp

logger = logging.getLogger(__name__)

MCP_PORT = 3000
MCP_HEALTH_URL = f"http://localhost:{MCP_PORT}/health"
MCP_CALL_URL = f"http://localhost:{MCP_PORT}/call"
IDLE_TIMEOUT = 300  # 5 นาที

_process: subprocess.Popen | None = None
_last_used: float = 0.0
_lock = threading.Lock()
_watchdog_started = False


def _is_alive() -> bool:
    return _process is not None and _process.poll() is None


async def ensure_running() -> None:
    global _process, _last_used, _watchdog_started

    with _lock:
        if _is_alive():
            _last_used = time.monotonic()
            return

        logger.info("Starting MCP server on port %d...", MCP_PORT)
        _process = subprocess.Popen(
            ["python", "mock_mcp_server.py", "--port", str(MCP_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    # รอจน health check ผ่าน
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    MCP_HEALTH_URL,
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    if resp.status == 200:
                        logger.info("MCP server ready (pid=%d)", _process.pid)
                        with _lock:
                            _last_used = time.monotonic()
                        if not _watchdog_started:
                            _watchdog_started = True
                            threading.Thread(
                                target=_idle_watchdog, daemon=True
                            ).start()
                        return
        except (aiohttp.ClientError, OSError):
            pass
        await asyncio.sleep(1)

    raise RuntimeError("MCP server failed to start within 45s")


async def call_tool(tool_name: str, args: dict) -> dict:
    with _lock:
        _update_last_used()

    async with aiohttp.ClientSession() as session:
        async with session.post(
            MCP_CALL_URL,
            json={"tool": tool_name, "args": args},
            timeout=aiohttp.ClientTimeout(total=55),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", data)


async def call_api(endpoint: str, body: dict | None = None) -> dict:
    with _lock:
        _update_last_used()

    async with aiohttp.ClientSession() as session:
        async with session.post(
            endpoint,
            json=body or {},
            timeout=aiohttp.ClientTimeout(total=55),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


def stop() -> None:
    global _process
    with _lock:
        if _is_alive():
            logger.info("Stopping MCP server (pid=%d)...", _process.pid)
            _process.terminate()
            try:
                _process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _process.kill()
                _process.wait(timeout=5)
            logger.info("MCP server stopped")
        _process = None


def _update_last_used() -> None:
    global _last_used
    _last_used = time.monotonic()


def _idle_watchdog() -> None:
    global _watchdog_started
    logger.info("Idle watchdog started (timeout=%ds)", IDLE_TIMEOUT)
    while True:
        time.sleep(30)
        with _lock:
            if not _is_alive():
                break
            idle = time.monotonic() - _last_used
            if idle > IDLE_TIMEOUT:
                logger.info("MCP idle %.0fs > %ds, auto-stopping", idle, IDLE_TIMEOUT)
                stop()
                break
    _watchdog_started = False
    logger.info("Idle watchdog exited")
