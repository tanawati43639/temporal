"""MCP Activities — 3 ตัว ครบจบในแต่ละ activity

แต่ละ activity:
  1. ensure MCP running (lazy start)
  2. เรียก tool
  3. return ผลลัพธ์

ไม่ต้อง pin worker, ไม่ต้อง session — ตัวไหนรับงานก็ start เอง
"""

from temporalio import activity

from workflows import mcp_manager
from workflows.models import ToolInput, ToolOutput


@activity.defn
async def fetch_customer(customer_id: str) -> ToolOutput:
    await mcp_manager.ensure_running()
    result = await mcp_manager.call_tool("fetch_customer", {
        "customer_id": customer_id,
    })
    return ToolOutput(result=result)


@activity.defn
async def enrich_profile(customer_data: dict) -> ToolOutput:
    await mcp_manager.ensure_running()
    result = await mcp_manager.call_tool("enrich_profile", {
        "customer": customer_data,
    })
    return ToolOutput(result=result)



@activity.defn
async def send_notification(email: str, customer_name: str) -> ToolOutput:
    await mcp_manager.ensure_running()
    result = await mcp_manager.call_tool("send_notification", {
        "email": email,
        "subject": f"Profile updated: {customer_name}",
        "body": f"Hi {customer_name}, your profile has been enriched.",
    })
    return ToolOutput(result=result)
