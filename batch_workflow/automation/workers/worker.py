"""Static worker — registers the batch process and its objects explicitly.

Run:  python -m automation.workers.worker
      python -m automation.workers.worker --identity worker-1 --sdk-port 8077
"""

import argparse
import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import Worker

from automation.config.queues import BATCH_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.objects.email.activities import send_email
from automation.objects.items.activities import process_item
from automation.objects.sharepoint.activities import SharePointObject, build_graph_client
from automation.processes.batch.parent import BatchParentWorkflow
from automation.processes.batch.process_batch import ProcessBatchWorkflow
from automation.processes.notify.notify_workflow import NotifyWorkflow
from automation.workers.metrics_exporter import start_metrics_exporter


def _otel_interceptors():
    """Optional OpenTelemetry tracing, enabled with TEMPORAL_OTEL=1.

    Sends per-workflow / per-activity spans to an OTLP collector (e.g. Jaeger).
    Gated by env so the default run never needs the opentelemetry packages.
    """
    if os.environ.get("TEMPORAL_OTEL") != "1":
        return []
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from temporalio.contrib.opentelemetry import TracingInterceptor

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    provider = TracerProvider(resource=Resource.create({"service.name": "batch-worker"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    logging.getLogger(__name__).info("OpenTelemetry tracing -> %s", endpoint)
    return [TracingInterceptor()]


async def run_worker(
    identity: str = "worker-1",
    sdk_port: int = 8077,
    exporter_port: int = 8078,
) -> None:
    logging.basicConfig(level=logging.INFO)

    # Expose SDK metrics on the given port. global_tags adds worker="<identity>"
    # to every metric so the Grafana dashboard can break results down per worker.
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

    start_metrics_exporter(client, BATCH_QUEUE, identity=identity, port=exporter_port)

    # Class-based object: build the shared Graph client once (auth via Key Vault),
    # then register its bound activity methods.
    sharepoint = SharePointObject(await build_graph_client())

    worker = Worker(
        client,
        task_queue=BATCH_QUEUE,
        workflows=[BatchParentWorkflow, ProcessBatchWorkflow, NotifyWorkflow],
        activities=[process_item, send_email, sharepoint.upload_file],
        max_concurrent_activities=50,
        interceptors=interceptors,
    )
    print(
        f"Worker '{identity}' started on '{BATCH_QUEUE}' "
        f"(SDK metrics :{sdk_port}, extra metrics :{exporter_port})"
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Temporal batch worker")
    parser.add_argument("--identity", default="worker-1", help="worker identity / metric label")
    parser.add_argument("--sdk-port", type=int, default=8077, help="SDK Prometheus port")
    parser.add_argument("--exporter-port", type=int, default=8078, help="CPU/backlog exporter port")
    args = parser.parse_args()
    asyncio.run(
        run_worker(
            identity=args.identity,
            sdk_port=args.sdk_port,
            exporter_port=args.exporter_port,
        )
    )


if __name__ == "__main__":
    main()
