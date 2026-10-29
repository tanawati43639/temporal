"""API registration for this process — the one file the registry discovers.

Exports ``SPECS``: the list of WorkflowSpec this process exposes over REST.
The request schema(s) live here too, next to the builder that maps them onto
the workflow input. Nothing outside this process edits the API layer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from automation.api.spec import QuerySpec, SignalSpec, UpdateSpec, WorkflowSpec

from .configs.queues import BATCH_QUEUE
from .models.batch import ParentInput
from .workflows.parent import ControllableBatchParentWorkflow


class StartControllableBatchRequest(BaseModel):
    total_items: int = Field(default=1000, description="Total items to process")
    batch_size: int = Field(default=100, description="Items per child batch")
    concurrency: int = Field(default=5, description="Max concurrent child workflows")
    batches_per_run: int = Field(
        default=4, description="Batches before continue-as-new"
    )


def _input_builder(r: StartControllableBatchRequest) -> ParentInput:
    return ParentInput(
        total_items=r.total_items,
        batch_size=r.batch_size,
        max_concurrent_children=r.concurrency,
        batches_per_run=r.batches_per_run,
    )


SPECS: list[WorkflowSpec] = [
    WorkflowSpec(
        name="controllable-batch",
        display_name="Controllable Batch",
        description="Fan-out batch workflow with pause/resume/stop controls",
        workflow_class=ControllableBatchParentWorkflow,
        run_method=ControllableBatchParentWorkflow.run,
        task_queue=BATCH_QUEUE,
        id_prefix="ctl-batch",
        start_body_model=StartControllableBatchRequest,
        start_input_builder=_input_builder,
        signals={
            "pause": SignalSpec(
                ControllableBatchParentWorkflow.request_pause,
                description="Pause at the next window boundary",
            ),
            "resume": SignalSpec(
                ControllableBatchParentWorkflow.request_resume,
                description="Clear the pause flag",
            ),
            "stop": SignalSpec(
                ControllableBatchParentWorkflow.request_stop,
                description="Graceful stop — finish in-flight, return summary",
            ),
        },
        queries={
            "state": QuerySpec(
                ControllableBatchParentWorkflow.state,
                description="running | paused | stopping",
            ),
            "progress": QuerySpec(
                ControllableBatchParentWorkflow.progress,
                description="State + offset + processed + failed",
            ),
        },
        updates={
            "pause-wait": UpdateSpec(
                ControllableBatchParentWorkflow.pause_and_wait,
                description="Pause and block until actually paused; returns snapshot",
            ),
        },
    ),
]
