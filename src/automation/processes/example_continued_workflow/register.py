"""API registration for the continuous dispatcher slice."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from automation.api.spec import QuerySpec, SignalSpec, WorkflowSpec

from .configs.queues import EXAMPLE_CONTINUED_QUEUE
from .models.continued import ContinuedInput
from .workflows.continued import ExampleContinuedWorkflow


class StartExampleContinuedRequest(BaseModel):
    run_seconds: int = Field(
        default=300, description="How long to keep generating items before stopping"
    )


def _input_builder(r: StartExampleContinuedRequest) -> ContinuedInput:
    stop_time = (
        datetime.now(timezone.utc) + timedelta(seconds=r.run_seconds)
    ).isoformat()
    return ContinuedInput(stop_time=stop_time)


SPECS: list[WorkflowSpec] = [
    WorkflowSpec(
        name="example-continued",
        display_name="Example Continued",
        description=(
            "Continuously generate items and spawn a child per item until a "
            "deadline — a continue-as-new dispatcher"
        ),
        workflow_class=ExampleContinuedWorkflow,
        run_method=ExampleContinuedWorkflow.run,
        task_queue=EXAMPLE_CONTINUED_QUEUE,
        id_prefix="continued",
        start_body_model=StartExampleContinuedRequest,
        start_input_builder=_input_builder,
        signals={
            "stop": SignalSpec(
                ExampleContinuedWorkflow.request_stop,
                description="Stop generating; finish the current poll then return",
            ),
        },
        queries={
            "state": QuerySpec(
                ExampleContinuedWorkflow.state, description="running | stopping"
            ),
            "progress": QuerySpec(
                ExampleContinuedWorkflow.progress,
                description="State + generated count + next_seq",
            ),
        },
    ),
]
