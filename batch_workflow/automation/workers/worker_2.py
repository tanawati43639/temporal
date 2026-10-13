"""Second worker on the same task queue (different identity + metric ports).

    SDK metrics  :8079   (add this target to prometheus.yml)
    extra export :8081   (add this target to prometheus.yml)

Run:  python -m automation.workers.worker_2   (while worker also runs)
"""

import asyncio

from automation.workers.worker import run_worker

if __name__ == "__main__":
    asyncio.run(run_worker(identity="worker-2", sdk_port=8079, exporter_port=8081))
