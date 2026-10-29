"""Data for the continuous dispatcher. Plain dataclasses, serializable, and the
input fields that must survive continue-as-new are carried explicitly.
"""

from dataclasses import dataclass


@dataclass
class ContinuedInput:
    # Per-invocation input: the only thing a caller supplies.
    stop_time: str  # ISO-8601 UTC deadline; compared against workflow.now()
    # State carried across continue-as-new (not caller-supplied).
    next_seq: int = 0
    generated: int = 0


@dataclass
class ItemInput:
    seq: int
    payload: str


@dataclass
class ItemResult:
    seq: int
    ok: bool


@dataclass
class ContinuedSummary:
    generated: int
    reason: str  # "deadline" | "stopped"
