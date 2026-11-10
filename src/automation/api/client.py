"""Shared Temporal client — one connection per namespace, reused across
endpoints.

Lives in its own module so factory.py and server.py can both import it
without circular references.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config

logger = logging.getLogger(__name__)

_clients: dict[str, Client] = {}


async def get_client(namespace: str | None = None) -> Client:
    """Return a connected Temporal client for *namespace* (default from env)."""
    ns = namespace or TEMPORAL_NAMESPACE
    if ns not in _clients:
        _clients[ns] = await Client.connect(
            TEMPORAL_ADDRESS, namespace=ns, tls=get_tls_config(),
        )
        logger.info("Connected to Temporal at %s (%s)", TEMPORAL_ADDRESS, ns)
    return _clients[ns]


@asynccontextmanager
async def lifespan(_app):
    """FastAPI lifespan: pre-connect the default namespace, clean up on shutdown."""
    await get_client()
    yield
    _clients.clear()
