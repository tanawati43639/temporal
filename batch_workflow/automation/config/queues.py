"""Task Queue names — the Temporal equivalent of Blue Prism Work Queues.

Keep every queue name here so processes, workers and clients agree on them.
Split queues by *resource profile*: cheap API work vs heavy UI automation
should not share a queue (they scale differently).
"""

BATCH_QUEUE = "batch-task-queue"        # heavy fan-out batch work
APPROVAL_QUEUE = "approval-task-queue"  # add new process queues here
MCP_SHARED_QUEUE = "mcp-shared-queue"  # MCP acquire + workflow dispatch
# UI_QUEUE = "ui-automation-queue"      # Playwright/Selenium screen work
