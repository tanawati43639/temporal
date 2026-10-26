"""ตัวอย่าง activity — งาน API-only (I/O-bound). สลับเป็นงานจริงของคุณได้เลย."""

import logging

import aiohttp
from temporalio import activity

log = logging.getLogger("activity")


@activity.defn
async def call_api(url: str) -> dict:
    """เรียก API ภายนอก แล้วคืน response.

    เพราะเป็น async + รอ I/O เป็นหลัก → activity แบบนี้รันพร้อมกันได้เยอะ
    ต่อ worker (ปรับด้วย MAX_CONCURRENT_ACTIVITIES).
    """
    activity.logger.info("เรียก API: %s", url)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            return {"status": resp.status, "data": await resp.json()}
