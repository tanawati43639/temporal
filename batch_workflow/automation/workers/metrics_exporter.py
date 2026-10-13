"""Extra Prometheus metrics for the worker, exposed on a dedicated port.

The Temporal SDK already exposes workflow/activity metrics on the SDK port. That
endpoint does *not* include process CPU/disk, nor the server-side task-queue
backlog. This module fills both gaps:

  * worker_* gauges  -> process CPU / memory / disk, sampled with psutil,
    tagged with worker="<identity>" so two workers can be told apart
  * temporal_task_queue_* gauges -> pulled from the Temporal server via
    DescribeTaskQueue(report_stats=True): backlog count/age, add/dispatch rate,
    and the number of pollers (workers) currently serving the queue

Prometheus already scrapes host.docker.internal:8078 (see
deployment/prometheus/prometheus.yml); add :8081 for a second worker.
"""

import asyncio
import logging
import os

import psutil
from prometheus_client import Gauge, start_http_server
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client

logger = logging.getLogger(__name__)

# --- Process / host resource gauges (per worker) ----------------------------
PROC_CPU = Gauge("worker_process_cpu_percent", "Worker process CPU usage (%, can exceed 100 on multi-core)", ["worker"])
SYS_CPU = Gauge("worker_system_cpu_percent", "Whole-host CPU usage (%)", ["worker"])
PROC_RSS = Gauge("worker_process_memory_rss_bytes", "Worker process resident memory (bytes)", ["worker"])
PROC_MEM_PCT = Gauge("worker_process_memory_percent", "Worker process memory usage (% of host RAM)", ["worker"])
PROC_THREADS = Gauge("worker_process_num_threads", "Worker process thread count", ["worker"])
PROC_FDS = Gauge("worker_process_open_fds", "Worker process open file descriptors", ["worker"])
DISK_USED_PCT = Gauge("worker_disk_used_percent", "Disk usage (%)", ["worker", "path"])
DISK_FREE = Gauge("worker_disk_free_bytes", "Disk free space (bytes)", ["worker", "path"])

# --- Task-queue gauges (server-side, via DescribeTaskQueue) -----------------
# These describe the shared queue, so both workers report the same values;
# the dashboard uses max by (type) to de-duplicate.
BACKLOG_COUNT = Gauge(
    "temporal_task_queue_backlog_count",
    "Approximate number of tasks waiting in the task queue",
    ["task_queue", "type"],
)
BACKLOG_AGE = Gauge(
    "temporal_task_queue_backlog_age_seconds",
    "Age of the oldest task in the backlog (seconds)",
    ["task_queue", "type"],
)
ADD_RATE = Gauge(
    "temporal_task_queue_tasks_add_rate",
    "Rate at which tasks are being added to the queue (tasks/sec)",
    ["task_queue", "type"],
)
DISPATCH_RATE = Gauge(
    "temporal_task_queue_tasks_dispatch_rate",
    "Rate at which tasks are being dispatched to workers (tasks/sec)",
    ["task_queue", "type"],
)
POLLERS = Gauge(
    "temporal_task_queue_pollers",
    "Number of pollers (workers) currently serving the task queue",
    ["task_queue", "type"],
)

_DISK_PATH = os.path.abspath(os.sep)  # "/" on posix
_TYPES = {
    "workflow": TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
    "activity": TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
}


async def _sample_resources(identity: str, interval: float) -> None:
    proc = psutil.Process()
    proc.cpu_percent(interval=None)  # prime; first call always returns 0.0
    psutil.cpu_percent(interval=None)
    while True:
        try:
            PROC_CPU.labels(worker=identity).set(proc.cpu_percent(interval=None))
            SYS_CPU.labels(worker=identity).set(psutil.cpu_percent(interval=None))
            mem = proc.memory_info()
            PROC_RSS.labels(worker=identity).set(mem.rss)
            PROC_MEM_PCT.labels(worker=identity).set(proc.memory_percent())
            PROC_THREADS.labels(worker=identity).set(proc.num_threads())
            try:
                PROC_FDS.labels(worker=identity).set(proc.num_fds())
            except (AttributeError, NotImplementedError):
                pass  # not available on Windows
            disk = psutil.disk_usage(_DISK_PATH)
            DISK_USED_PCT.labels(worker=identity, path=_DISK_PATH).set(disk.percent)
            DISK_FREE.labels(worker=identity, path=_DISK_PATH).set(disk.free)
        except Exception:
            logger.exception("resource sampling failed")
        await asyncio.sleep(interval)


async def _sample_backlog(client: Client, task_queue: str, interval: float) -> None:
    while True:
        for type_label, tq_type in _TYPES.items():
            try:
                resp = await client.workflow_service.describe_task_queue(
                    DescribeTaskQueueRequest(
                        namespace=client.namespace,
                        task_queue=TaskQueue(name=task_queue),
                        task_queue_type=tq_type,
                        report_stats=True,
                    )
                )
                stats = resp.stats
                labels = dict(task_queue=task_queue, type=type_label)
                BACKLOG_COUNT.labels(**labels).set(stats.approximate_backlog_count)
                BACKLOG_AGE.labels(**labels).set(stats.approximate_backlog_age.ToSeconds())
                ADD_RATE.labels(**labels).set(stats.tasks_add_rate)
                DISPATCH_RATE.labels(**labels).set(stats.tasks_dispatch_rate)
                POLLERS.labels(**labels).set(len(resp.pollers))
            except Exception:
                logger.exception("backlog sampling failed for %s", type_label)
        await asyncio.sleep(interval)


def start_metrics_exporter(
    client: Client,
    task_queue: str,
    identity: str = "worker-1",
    port: int = 8078,
    resource_interval: float = 2.0,
    backlog_interval: float = 5.0,
) -> None:
    """Start the exporter HTTP server and its background samplers.

    Call this from within a running event loop (e.g. inside the worker's
    async main) before `worker.run()`.
    """
    start_http_server(port)
    logger.info("Extra worker metrics for '%s' on :%d (CPU/disk + task-queue backlog)", identity, port)
    asyncio.create_task(_sample_resources(identity, resource_interval))
    asyncio.create_task(_sample_backlog(client, task_queue, backlog_interval))
