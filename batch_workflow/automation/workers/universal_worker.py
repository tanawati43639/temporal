"""Universal worker: auto-discovers and registers every workflow (process) and
activity (object) in the codebase, then binds to a chosen task queue.

Why this works (and the limit): a Temporal worker must have the workflow/activity
*code* locally — the server only stores history, never implementations, so a
worker cannot download code for types it has never seen. "Universal" means
"register everything this repo defines without a hand-maintained list", not
"fetch arbitrary code from the server". You pick the task queue; the processes
and objects are discovered from the code.

Run:
    python -m automation.workers.universal_worker --task-queue batch-task-queue
    python -m automation.workers.universal_worker --task-queue q --packages automation.processes,automation.objects
    python -m automation.workers.universal_worker --task-queue q --identity uw-2 --sdk-port 8079 --exporter-port 8081
"""

import argparse
import asyncio
import importlib
import inspect
import logging
import pkgutil

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import Worker

from automation.config.queues import BATCH_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.workers.metrics_exporter import start_metrics_exporter
from automation.workers.worker import _otel_interceptors

logger = logging.getLogger(__name__)

# Packages that hold processes (workflows) and objects (activities).
DEFAULT_PACKAGES = ["automation.processes", "automation.objects"]


def _module_names(packages: list[str]) -> list[str]:
    """Recursively list every non-package module under the given packages."""
    names: list[str] = []
    for pkg_name in packages:
        try:
            pkg = importlib.import_module(pkg_name)
        except Exception as e:
            logger.warning("skip package %r: %s", pkg_name, e)
            continue
        if not hasattr(pkg, "__path__"):  # a plain module, not a package
            names.append(pkg_name)
            continue
        for mod in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            if not mod.ispkg:
                names.append(mod.name)
    return names


def discover(packages: list[str] | None = None) -> tuple[list[type], list]:
    """Scan packages and return (workflow_classes, activity_callables).

    Detection uses the markers the SDK decorators attach:
      @workflow.defn  -> class has __temporal_workflow_definition
      @activity.defn  -> callable has __temporal_activity_definition
    De-duplicated by registered name so a symbol imported into several modules
    is registered once.
    """
    workflows: dict[str, type] = {}
    activities: dict[str, object] = {}

    for name in _module_names(packages or DEFAULT_PACKAGES):
        try:
            mod = importlib.import_module(name)
        except Exception as e:  # a bad/optional module shouldn't kill the worker
            logger.warning("skip module %r: %s", name, e)
            continue

        for _, obj in inspect.getmembers(mod):
            if inspect.isclass(obj) and hasattr(obj, "__temporal_workflow_definition"):
                d = workflow._Definition.from_class(obj)
                key = d.name or obj.__qualname__  # dynamic workflows have name=None
                workflows.setdefault(key, obj)
            elif callable(obj) and hasattr(obj, "__temporal_activity_definition"):
                d = activity._Definition.from_callable(obj)
                if d is not None:
                    key = d.name or getattr(obj, "__qualname__", repr(obj))
                    activities.setdefault(key, obj)

    return list(workflows.values()), list(activities.values())


def _activity_builders(packages: list[str] | None = None) -> list:
    """Find module-level `build_object_activities` factories (for class-based
    objects that need a shared client built before registration)."""
    builders = []
    for name in _module_names(packages or DEFAULT_PACKAGES):
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        fn = getattr(mod, "build_object_activities", None)
        if callable(fn):
            builders.append(fn)
    return builders


async def run(
    task_queue: str,
    packages: list[str] | None = None,
    identity: str = "universal-worker",
    sdk_port: int = 8077,
    exporter_port: int = 8078,
    max_concurrent_activities: int = 50,
) -> None:
    logging.basicConfig(level=logging.INFO)

    wfs, acts = discover(packages)
    # Class-based objects contribute their bound activities via a factory hook.
    for build in _activity_builders(packages):
        acts.extend(await build())
    if not wfs and not acts:
        raise SystemExit("No @workflow.defn / @activity.defn found — nothing to register.")
    logger.info(
        "Discovered %d process(es): %s",
        len(wfs),
        ", ".join(workflow._Definition.from_class(w).name for w in wfs),
    )
    logger.info(
        "Discovered %d object activity(ies): %s",
        len(acts),
        ", ".join(activity._Definition.from_callable(a).name for a in acts),
    )

    runtime = Runtime(
        telemetry=TelemetryConfig(
            metrics=PrometheusConfig(
                bind_address=f"0.0.0.0:{sdk_port}",
                counters_total_suffix=True,
                unit_suffix=True,
                durations_as_seconds=True,
            ),
            global_tags={"worker": identity},
        )
    )
    interceptors = _otel_interceptors()
    client = await Client.connect(
        TEMPORAL_ADDRESS, runtime=runtime, identity=identity, interceptors=interceptors
    )

    start_metrics_exporter(client, task_queue, identity=identity, port=exporter_port)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=wfs,
        activities=acts,
        max_concurrent_activities=max_concurrent_activities,
        interceptors=interceptors,
    )
    print(
        f"Universal worker '{identity}' on '{task_queue}' "
        f"({len(wfs)} processes, {len(acts)} objects; "
        f"SDK metrics :{sdk_port}, extra :{exporter_port})"
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal auto-discovering Temporal worker")
    parser.add_argument("--task-queue", default=BATCH_QUEUE, help="task queue to serve")
    parser.add_argument(
        "--packages",
        default=None,
        help="comma-separated packages to scan (default: automation.processes,automation.objects)",
    )
    parser.add_argument("--identity", default="universal-worker", help="worker identity / metric label")
    parser.add_argument("--sdk-port", type=int, default=8077, help="SDK Prometheus port")
    parser.add_argument("--exporter-port", type=int, default=8078, help="CPU/backlog exporter port")
    parser.add_argument("--max-concurrent-activities", type=int, default=50)
    args = parser.parse_args()

    packages = [p.strip() for p in args.packages.split(",")] if args.packages else None
    asyncio.run(
        run(
            task_queue=args.task_queue,
            packages=packages,
            identity=args.identity,
            sdk_port=args.sdk_port,
            exporter_port=args.exporter_port,
            max_concurrent_activities=args.max_concurrent_activities,
        )
    )


if __name__ == "__main__":
    main()
