"""Data models for the approval (human-in-the-loop) process.

Maps to Blue Prism Data Items — plain dataclasses, no side effects.
"""

from dataclasses import dataclass, field
from enum import Enum


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    TIMED_OUT = "timed_out"


@dataclass
class ApprovalRequest:
    """Input to start the approval workflow."""

    requester: str  # who is requesting (e.g. email)
    request_type: str  # e.g. "leave", "purchase", "access"
    description: str
    approver: str  # who should approve (e.g. manager email)
    amount: float = 0.0  # optional: dollar amount for purchase requests
    timeout_hours: int = 72  # auto-escalate/reject after this many hours


@dataclass
class ApprovalDecision:
    """Signal payload: the human's decision."""

    approved: bool
    comment: str = ""
    decided_by: str = ""  # who actually clicked approve/reject


@dataclass
class ApprovalState:
    """Full workflow state — exposed via query."""

    request: ApprovalRequest | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision: ApprovalDecision | None = None
    escalation_level: int = 0
    history: list[str] = field(default_factory=list)
