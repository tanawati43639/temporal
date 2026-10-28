"""Pydantic request/response models for the registry-driven API.

Each `Start*Request` corresponds to one workflow's input. Keeping them in
one place makes it easy to see the full surface of every workflow at a
glance, and lets the registry attach the right form to each endpoint.

Signal and update bodies live here too (if the signal/update takes args).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ─── start: controllable batch ─────────────────────────────────────
class StartControllableBatchRequest(BaseModel):
    total_items: int = Field(default=1000, description="Total items to process")
    batch_size: int = Field(default=100, description="Items per child batch")
    concurrency: int = Field(default=5, description="Max concurrent child workflows")
    batches_per_run: int = Field(
        default=4, description="Batches before continue-as-new"
    )


# ─── start: plain batch (same shape, kept distinct in Swagger) ────
class StartBatchRequest(StartControllableBatchRequest):
    pass


# ─── start: approval ──────────────────────────────────────────────
class StartApprovalRequest(BaseModel):
    requester: str = Field(default="alice@example.com", description="Requester email")
    approver: str = Field(default="bob-manager@example.com", description="Approver email")
    request_type: str = Field(default="leave", description="leave | purchase | access")
    description: str = "Annual leave request"
    amount: float = 0.0
    timeout_hours: int = 72


# ─── signal body: approval decision ──────────────────────────────
class DecideRequest(BaseModel):
    approved: bool
    comment: str = ""
    decided_by: str = ""


# ─── update body: approval amount ────────────────────────────────
class UpdateAmountRequest(BaseModel):
    new_amount: float


# ─── start: notify ────────────────────────────────────────────────
class StartNotifyRequest(BaseModel):
    recipient: str = "user@example.com"
    report_name: str = "monthly-report.pdf"
    report_ref: str = Field(
        default="s3://bucket/key", description="Pointer/URL to the report content"
    )


# ─── start: mcp ───────────────────────────────────────────────────
class McpToolInputModel(BaseModel):
    tool_name: str
    args: dict = Field(default_factory=dict)


class StartMcpRequest(BaseModel):
    tasks: list[McpToolInputModel] = Field(default_factory=list)
