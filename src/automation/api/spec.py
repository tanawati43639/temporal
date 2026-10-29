"""Shared API vocabulary — the dataclasses every process uses to declare the
REST surface of its workflows.

A process describes its workflows by exporting a ``SPECS: list[WorkflowSpec]``
from its ``register.py``. The API layer (registry + factory) is the only thing
that reads these; it mounts endpoints from them without any per-process code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel


@dataclass
class SignalSpec:
    """One signal exposed via REST."""

    fn: Any  # unbound method on the workflow class
    body_model: type[BaseModel] | None = None  # None = no payload
    body_builder: Callable[[Any], Any] | None = None
    description: str = ""


@dataclass
class QuerySpec:
    fn: Any
    description: str = ""


@dataclass
class UpdateSpec:
    fn: Any
    body_model: type[BaseModel] | None = None
    body_builder: Callable[[Any], Any] | None = None
    description: str = ""


@dataclass
class WorkflowSpec:
    name: str  # URL slug, e.g. "controllable-batch"
    display_name: str  # Swagger tag label
    description: str
    workflow_class: Any
    run_method: Any  # workflow_class.run — used by the typed start overload
    task_queue: str
    id_prefix: str
    start_body_model: type[BaseModel]
    # Convert the Pydantic request into the workflow input (dataclass/primitive).
    start_input_builder: Callable[[BaseModel], Any]
    signals: dict[str, SignalSpec] = field(default_factory=dict)
    queries: dict[str, QuerySpec] = field(default_factory=dict)
    updates: dict[str, UpdateSpec] = field(default_factory=dict)
