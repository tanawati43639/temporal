"""Central (cross-process) configuration — lives outside the ``automation``
package because it is shared by every worker, client and the API, and is
environment-level, not process-level.

Values resolve in this order: real environment variables first, then the repo
``.env`` file (dev convenience), then the hard-coded defaults below. So a value
exported in the shell or set by the deploy platform always wins over ``.env``.

Process-specific config (task-queue names, concurrency tuning) does NOT live
here — it belongs to each process's own ``configs/`` package.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from temporalio.client import TLSConfig

# Load <repo>/.env regardless of the current working directory. override=False
# keeps real env vars authoritative over the file.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TEMPORAL_UI_BASE = os.environ.get("TEMPORAL_UI_BASE", "http://localhost:8080")

TEMPORAL_TLS_CLIENT_CERT = os.environ.get("TEMPORAL_TLS_CLIENT_CERT", "")
TEMPORAL_TLS_CLIENT_KEY = os.environ.get("TEMPORAL_TLS_CLIENT_KEY", "")
TEMPORAL_TLS_ROOT_CA = os.environ.get("TEMPORAL_TLS_ROOT_CA", "")


def get_tls_config() -> TLSConfig | None:
    """Build a ``TLSConfig`` from env-var paths, or *None* for plaintext."""
    if not TEMPORAL_TLS_CLIENT_CERT:
        return None
    root = Path(__file__).resolve().parent.parent
    client_cert = (root / TEMPORAL_TLS_CLIENT_CERT).read_bytes()
    client_key = (root / TEMPORAL_TLS_CLIENT_KEY).read_bytes()
    server_root_ca = (root / TEMPORAL_TLS_ROOT_CA).read_bytes() if TEMPORAL_TLS_ROOT_CA else None
    return TLSConfig(
        client_cert=client_cert,
        client_private_key=client_key,
        server_root_ca_cert=server_root_ca,
    )


def temporal_ui_link(workflow_id: str) -> str:
    return f"{TEMPORAL_UI_BASE}/namespaces/{TEMPORAL_NAMESPACE}/workflows/{workflow_id}"
