"""Data models passed between processes and objects — the Temporal equivalent
of Blue Prism Data Items / Collections. Plain dataclasses only, no side effects.
"""

from dataclasses import dataclass


@dataclass
class ParentInput:
    total_items: int
    batch_size: int = 100
    # Number of child workflows running at the same time
    max_concurrent_children: int = 5
    # Batches per run before continue-as-new (keeps parent history small)
    batches_per_run: int = 20
    # State carried across continue-as-new
    next_offset: int = 0
    processed: int = 0
    failed: int = 0


@dataclass
class BatchInput:
    batch_id: int
    start: int  # inclusive
    end: int  # exclusive


@dataclass
class BatchResult:
    batch_id: int
    processed: int
    failed: int
    failed_items: list[int]


@dataclass
class BatchSummary:
    total_items: int
    processed: int
    failed: int
