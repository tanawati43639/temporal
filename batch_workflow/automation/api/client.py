"""Shared Temporal client — singleton used by every API endpoint.

Lives in its own module so factory.py and server.py can both import it
without circular references.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from temporalio.client import Client

from automation.config.settings import TEMPORAL_ADDRESS

logger = logging.getLogger(__name__)

_client: Client | None = None


async def get_client() -> Client:
    """Return a connected Temporal client, creating it on first use."""
    global _client
    if _client is None:
        _client = await Client.connect(TEMPORAL_ADDRESS)
    return _client


@asynccontextmanager
async def lifespan(_app):
    """FastAPI lifespan: connect on startup, drop reference on shutdown."""
    global _client
    _client = await Client.connect(TEMPORAL_ADDRESS)
    logger.info("Connected to Temporal at %s", TEMPORAL_ADDRESS)
    yield
    _client = None
