"""Mock MCP Server — จำลอง MCP server ที่มี 3 tools

Tools:
  - fetch_customer:    ดึงข้อมูลลูกค้า (จำลอง API call)
  - enrich_profile:    เพิ่มข้อมูล profile (จำลอง processing)
  - send_notification: ส่งแจ้งเตือน (จำลอง side effect)

Run:  python mock_mcp_server.py
      python mock_mcp_server.py --port 3000
"""

import argparse
import asyncio
import json
import random
import logging
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-server")

CUSTOMERS = {
    "C001": {"name": "Alice", "email": "alice@example.com", "tier": "gold"},
    "C002": {"name": "Bob", "email": "bob@example.com", "tier": "silver"},
    "C003": {"name": "Charlie", "email": "charlie@example.com", "tier": "bronze"},
    "C004": {"name": "Diana", "email": "diana@example.com", "tier": "gold"},
    "C005": {"name": "Eve", "email": "eve@example.com", "tier": "platinum"},
}

notifications_sent: list[dict] = []


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_call(request: web.Request) -> web.Response:
    body = await request.json()
    tool = body.get("tool")
    args = body.get("args", {})

    logger.info("Tool call: %s(%s)", tool, json.dumps(args, ensure_ascii=False))

    if tool == "fetch_customer":
        return await _fetch_customer(args)
    elif tool == "enrich_profile":
        return await _enrich_profile(args)
    elif tool == "send_notification":
        return await _send_notification(args)
    else:
        return web.json_response({"error": f"Unknown tool: {tool}"}, status=400)


async def _fetch_customer(args: dict) -> web.Response:
    await asyncio.sleep(random.uniform(0.5, 1.5))

    customer_id = args.get("customer_id")
    if customer_id not in CUSTOMERS:
        return web.json_response({"error": f"Customer {customer_id} not found"}, status=404)

    customer = CUSTOMERS[customer_id].copy()
    customer["customer_id"] = customer_id
    return web.json_response({"result": customer})


async def _enrich_profile(args: dict) -> web.Response:
    await asyncio.sleep(random.uniform(0.3, 1.0))

    customer = args.get("customer", {})
    enriched = customer.copy()
    enriched["loyalty_points"] = random.randint(100, 9999)
    enriched["last_purchase"] = "2026-10-01"
    enriched["risk_score"] = round(random.uniform(0.1, 0.9), 2)
    enriched["enriched"] = True
    return web.json_response({"result": enriched})


async def _send_notification(args: dict) -> web.Response:
    await asyncio.sleep(random.uniform(0.2, 0.8))

    notification = {
        "to": args.get("email"),
        "subject": args.get("subject", "Notification"),
        "body": args.get("body", ""),
        "status": "sent",
    }
    notifications_sent.append(notification)
    logger.info("Notification sent to %s", notification["to"])
    return web.json_response({"result": notification})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/call", handle_call)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock MCP Server")
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()

    logger.info("Starting Mock MCP Server on port %d", args.port)
    web.run_app(create_app(), port=args.port, print=None)
    logger.info("MCP Server stopped")


if __name__ == "__main__":
    main()
