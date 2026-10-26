#!/usr/bin/env python3
"""
Dump event history (JSON) ของทุก workflow ที่ start "วันนี้" ออกมาเป็นไฟล์
เทียบเท่า: temporal workflow show --workflow-id <id> --output json  (แต่ทำครบทุกตัว)

ใช้:
    pip install temporalio
    python dump_today_histories.py
    python dump_today_histories.py --address my-host:7233 --namespace prod --by close

ผลลัพธ์: ไฟล์ JSON ต่อ 1 workflow ในโฟลเดอร์ ./history_<YYYY-MM-DD>/
         ชื่อไฟล์ = <workflow_id>__<run_id>.json
"""

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.protobuf.json_format import MessageToJson
from temporalio.client import Client
from temporalio.api.history.v1 import History

LOCAL_TZ = ZoneInfo("Asia/Bangkok")
UTC = ZoneInfo("UTC")


def rfc3339_z(dt: datetime) -> str:
    """แปลงเป็น RFC3339 แบบ Zulu ที่ Temporal visibility query รับได้"""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_query(day: datetime, by: str) -> str:
    """สร้าง List Filter query สำหรับช่วง 1 วัน (เที่ยงคืนถึงเที่ยงคืนเวลา Bangkok)"""
    start_local = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    field = "StartTime" if by == "start" else "CloseTime"
    # by=close จะได้เฉพาะ workflow ที่ปิดแล้ววันนี้; by=start ได้ทั้ง open+closed ที่เริ่มวันนี้
    return f'{field} >= "{rfc3339_z(start_local)}" AND {field} < "{rfc3339_z(end_local)}"'


def safe_filename(*parts: str) -> str:
    raw = "__".join(parts)
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw) + ".json"


async def dump_one(client: Client, wf, out_dir: Path, snake_case: bool, sem: asyncio.Semaphore):
    async with sem:
        try:
            handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
            # fetch_history() ดึงทั้ง history; ถ้า workflow ยัง running จะได้ snapshot เท่าที่มีถึงตอนนี้
            wf_history = await handle.fetch_history()
            # ประกอบเป็น History proto แล้วแปลงเป็น JSON (proto3 JSON, enum เป็น string)
            history_proto = History(events=wf_history.events)
            body = MessageToJson(
                history_proto,
                preserving_proto_field_name=snake_case,  # True = ชื่อ field แบบ snake_case เหมือน CLI
                indent=2,
            )
            # ห่อ metadata ระดับ workflow ไว้ด้วย เพื่อให้ไฟล์ self-contained สำหรับ audit
            wrapper = {
                "workflowId": wf.id,
                "runId": wf.run_id,
                "workflowType": wf.workflow_type,
                "status": str(wf.status.name) if wf.status else None,
                "startTime": wf.start_time.isoformat() if wf.start_time else None,
                "closeTime": wf.close_time.isoformat() if wf.close_time else None,
                "taskQueue": wf.task_queue,
                "history": json.loads(body),
            }
            path = out_dir / safe_filename(wf.id, wf.run_id)
            path.write_text(json.dumps(wrapper, indent=2, ensure_ascii=False), encoding="utf-8")
            return (wf.id, True, None)
        except Exception as e:  # เก็บ error ต่อ workflow แล้วไปต่อ ไม่ให้ทั้ง batch ล้ม
            return (wf.id, False, repr(e))


async def main():
    ap = argparse.ArgumentParser(description="Dump today's Temporal workflow histories to JSON")
    ap.add_argument("--address", default=os.getenv("TEMPORAL_ADDRESS", "localhost:7233"))
    ap.add_argument("--namespace", default=os.getenv("TEMPORAL_NAMESPACE", "default"))
    ap.add_argument("--date", help="YYYY-MM-DD (default = วันนี้ตามเวลา Bangkok)")
    ap.add_argument("--by", choices=["start", "close"], default="start",
                    help="กรองด้วย StartTime หรือ CloseTime (default start)")
    ap.add_argument("--out", help="โฟลเดอร์ปลายทาง (default ./history_<date>)")
    ap.add_argument("--concurrency", type=int, default=10, help="จำนวน fetch พร้อมกัน")
    ap.add_argument("--snake-case", action="store_true",
                    help="ใช้ field name แบบ snake_case ให้เหมือน CLI --output json")
    args = ap.parse_args()

    day = (
        datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        if args.date
        else datetime.now(LOCAL_TZ)
    )
    out_dir = Path(args.out) if args.out else Path(f"history_{day.strftime('%Y-%m-%d')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    query = build_query(day, args.by)
    print(f"Connecting to {args.address} (namespace={args.namespace})")
    print(f"Query: {query}")

    # สำหรับ Temporal Cloud: ใส่ tls=True และ api_key / mTLS ตรงนี้
    client = await Client.connect(args.address, namespace=args.namespace)

    # เก็บ workflow ที่ match ทั้งหมด (async iterator paginate ให้เอง)
    workflows = [wf async for wf in client.list_workflows(query)]
    print(f"พบ {len(workflows)} workflow — กำลังดึง history...")

    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(
        *(dump_one(client, wf, out_dir, args.snake_case, sem) for wf in workflows)
    )

    ok = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    print(f"\nสำเร็จ {len(ok)} / ล้มเหลว {len(failed)} → ไฟล์อยู่ที่ {out_dir.resolve()}")
    for wf_id, _, err in failed:
        print(f"  [FAIL] {wf_id}: {err}")


if __name__ == "__main__":
    asyncio.run(main())