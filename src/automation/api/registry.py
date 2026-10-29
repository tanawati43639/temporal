"""Workflow registry — auto-aggregated from every process.

In this template each process is self-contained and declares its own API
surface by exporting ``SPECS: list[WorkflowSpec]`` from its ``register.py``.
This module discovers those modules under ``automation.processes`` and merges
them into one list. Adding a new process requires NO edit here: drop a package
under ``processes/`` with a ``register.py`` and it shows up automatically.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

import automation.processes as _processes_pkg

from .spec import WorkflowSpec

logger = logging.getLogger(__name__)


def discover_specs() -> list[WorkflowSpec]:
    """Import ``<process>.register`` for every process package and collect SPECS."""
    specs: list[WorkflowSpec] = []
    seen: set[str] = set()
    for mod in pkgutil.iter_modules(
        _processes_pkg.__path__, _processes_pkg.__name__ + "."
    ):
        if not mod.ispkg:
            continue
        register_name = f"{mod.name}.register"
        try:
            reg = importlib.import_module(register_name)
        except ModuleNotFoundError:
            continue  # process without a register.py is not exposed via the API
        except Exception as e:  # a broken register.py shouldn't kill the whole API
            logger.warning("skip %s: %s", register_name, e)
            continue
        for spec in getattr(reg, "SPECS", []):
            if spec.name in seen:
                logger.warning("duplicate workflow spec name %r — skipping", spec.name)
                continue
            seen.add(spec.name)
            specs.append(spec)
    return specs


WORKFLOWS: list[WorkflowSpec] = discover_specs()
