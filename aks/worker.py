"""
Temporal Worker — scale-in-pod edition.

หลักการ: worker ตัวเดียวรันได้หลายงานพร้อมกัน (concurrency) โดยปรับผ่าน env var
ทั้งหมด จะได้จูน throughput ต่อ pod ได้โดยไม่ต้อง rebuild image.

สำหรับงาน API-only (I/O-bound) ให้ตั้ง MAX_CONCURRENT_ACTIVITIES สูงๆ ได้
เพราะ worker ส่วนใหญ่รอ response ของ API ไม่ได้กิน CPU.
"""

import asyncio
import logging
import os
import signal
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

from activities import call_api
from workflows import ApiWorkflow

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("worker")


def _int(name: str, default: int) -> int:
    """อ่าน env var เป็น int พร้อม default."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        log.warning("ค่า %s ไม่ใช่ตัวเลข ใช้ default=%s", name, default)
        return default


# ---- connection config (ต่างกันระหว่าง dev/prod ผ่าน env) ----
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "api-tasks")

# ---- concurrency config (คือหัวใจของ "scale ภายใน pod") ----
# จำนวน activity ที่รันพร้อมกันได้ต่อ worker — ตัวที่ปรับบ่อยสุดสำหรับงาน API
MAX_CONCURRENT_ACTIVITIES = _int("MAX_CONCURRENT_ACTIVITIES", 100)
# จำนวน workflow task ที่ประมวลผลพร้อมกันได้
MAX_CONCURRENT_WORKFLOW_TASKS = _int("MAX_CONCURRENT_WORKFLOW_TASKS", 50)
# local activity (ถ้าใช้) — งานสั้นๆ ที่รันในเครื่อง worker เอง
MAX_CONCURRENT_LOCAL_ACTIVITIES = _int("MAX_CONCURRENT_LOCAL_ACTIVITIES", 50)
# จำนวน poller ที่ยิงไปขอ task จาก server — เพิ่มได้ถ้า latency การหยิบงานสูง
MAX_ACTIVITY_TASK_POLLS = _int("MAX_ACTIVITY_TASK_POLLS", 5)
MAX_WORKFLOW_TASK_POLLS = _int("MAX_WORKFLOW_TASK_POLLS", 5)
# sticky cache: จำนวน workflow ที่ cache ไว้ใน memory (ลดการ replay ประวัติ)
MAX_CACHED_WORKFLOWS = _int("MAX_CACHED_WORKFLOWS", 1000)
# rate limit ฝั่ง worker นี้ (0 = ไม่จำกัด) — กันยิง API ปลายทางแรงเกินไป
MAX_ACTIVITIES_PER_SECOND = _int("MAX_ACTIVITIES_PER_SECOND", 0)

# ---- graceful shutdown: ให้งานที่ค้างทำต่อให้จบก่อน pod ตาย ----
# สำคัญตอน scale down / rolling update — อย่าฆ่างานกลางคัน
GRACEFUL_SHUTDOWN_SECONDS = _int("GRACEFUL_SHUTDOWN_SECONDS", 30)


async def main() -> None:
    log.info("ต่อ Temporal ที่ %s (ns=%s)", TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE)
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)

    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[ApiWorkflow],
        activities=[call_api],
        # ---- ปรับ concurrency ตรงนี้ผ่าน env ----
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
        max_concurrent_workflow_tasks=MAX_CONCURRENT_WORKFLOW_TASKS,
        max_concurrent_local_activities=MAX_CONCURRENT_LOCAL_ACTIVITIES,
        max_concurrent_activity_task_polls=MAX_ACTIVITY_TASK_POLLS,
        max_concurrent_workflow_task_polls=MAX_WORKFLOW_TASK_POLLS,
        max_cached_workflows=MAX_CACHED_WORKFLOWS,
        max_activities_per_second=(
            MAX_ACTIVITIES_PER_SECOND if MAX_ACTIVITIES_PER_SECOND > 0 else None
        ),
        graceful_shutdown_timeout=timedelta(seconds=GRACEFUL_SHUTDOWN_SECONDS),
    )

    log.info(
        "เริ่ม worker | queue=%s | activities=%d workflows=%d cache=%d",
        TEMPORAL_TASK_QUEUE,
        MAX_CONCURRENT_ACTIVITIES,
        MAX_CONCURRENT_WORKFLOW_TASKS,
        MAX_CACHED_WORKFLOWS,
    )

    # รับ SIGTERM จาก Kubernetes เพื่อ shutdown อย่างนุ่มนวล
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async with worker:
        await stop.wait()
        log.info("ได้รับสัญญาณหยุด — กำลัง drain งานที่ค้าง (%ds)", GRACEFUL_SHUTDOWN_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
