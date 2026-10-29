"""Central (cross-process) configuration — lives outside the ``automation``
package because it is shared by every worker, client and the API, and is
environment-level, not process-level.

Values resolve in this order: real environment variables first, then the repo
``.env`` file (dev convenience), then the hard-coded defaults below. So a value
exported in the shell or set by the deploy platform always wins over ``.env``.

Process-specific config (task-queue names, concurrency tuning) does NOT live
here — it belongs to each process's own ``configs/`` package.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load <repo>/.env regardless of the current working directory. override=False
# keeps real env vars authoritative over the file.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TEMPORAL_UI_BASE = os.environ.get("TEMPORAL_UI_BASE", "http://localhost:8080")


def temporal_ui_link(workflow_id: str) -> str:
    return f"{TEMPORAL_UI_BASE}/namespaces/{TEMPORAL_NAMESPACE}/workflows/{workflow_id}"
