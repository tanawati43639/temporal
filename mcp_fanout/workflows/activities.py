"""MCP Activities — รวมทุกอย่างใน activity เดียว

ensure MCP running → เรียก tool/api → return ผลลัพธ์
ไม่ต้อง pin worker, ไม่ต้อง session — ตัวไหนรับงานก็ start เอง
"""

from temporalio import activity

from workflows import mcp_manager
from workflows.models import ApiInput, ToolInput, ToolOutput


@activity.defn
async def call_mcp_tool(input: ToolInput) -> ToolOutput:
    """เรียก tool บน MCP server (localhost)"""
    await mcp_manager.ensure_running()
    result = await mcp_manager.call_tool(input.tool_name, input.args)
    return ToolOutput(result=result)


@activity.defn
async def call_mcp_api(input: ApiInput) -> ToolOutput:
    """เรียก API ภายนอกผ่าน MCP server"""
    await mcp_manager.ensure_running()
    result = await mcp_manager.call_api(input.endpoint, input.body)
    return ToolOutput(result=result)
