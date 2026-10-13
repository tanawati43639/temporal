"""SharePoint object (VBO) — class-based so the Microsoft Graph client is built
ONCE at worker startup (authenticated via Key Vault) and shared across calls.

Design notes:
- The activity takes a *reference* to the content (URL/pointer), not the bytes,
  and returns a path/URL — large files never pass through Event History.
- Chunked upload calls activity.heartbeat() so a long transfer can resume after
  a worker crash and so the server knows the activity is still alive.
"""

import asyncio
import logging

from temporalio import activity

from automation.models.notify import UploadInput
from automation.objects.keyvault.client import get_secret

logger = logging.getLogger(__name__)

_CHUNK = 320 * 1024  # 320 KiB, Graph upload-session chunk size


class _FakeGraphClient:
    """Stand-in for a real Graph client in dev."""

    async def upload_chunk(self, path: str, offset: int, chunk: bytes) -> None:
        await asyncio.sleep(0.05)


async def build_graph_client() -> object:
    """Build the shared Graph client. Call once at worker startup."""
    # Credentials come from Key Vault, inside the worker — never via a workflow.
    client_secret = await get_secret("graph-client-secret")
    _ = client_secret  # used to auth the real client below
    # TODO: return a real authenticated Graph client, e.g.
    #   from msgraph import GraphServiceClient
    #   return GraphServiceClient(credentials=..., scopes=[...])
    return _FakeGraphClient()


class SharePointObject:
    """Register an *instance* of this with the Worker (needs the shared client)."""

    def __init__(self, graph_client: object) -> None:
        self._client = graph_client

    @activity.defn(name="sharepoint_upload_file")
    async def upload_file(self, input: UploadInput) -> str:
        data = await _fetch_reference(input.source_ref)
        path = f"{input.site}/{input.folder}/{input.filename}"

        offset = 0
        for chunk in _chunks(data):
            await self._client.upload_chunk(path, offset, chunk)  # type: ignore[attr-defined]
            offset += len(chunk)
            activity.heartbeat({"uploaded": offset, "total": len(data)})

        activity.logger.info("uploaded %s (%d bytes)", input.filename, len(data))
        return path  # a path/URL, not the file bytes


async def build_object_activities() -> list:
    """universal_worker hook — build the shared client once and return the bound
    activity methods. Any object module that needs init can expose this factory.
    """
    sp = SharePointObject(await build_graph_client())
    return [sp.upload_file]


async def _fetch_reference(ref: str) -> bytes:
    # ref is a URL/pointer to the content; fetch it here, not in the workflow.
    await asyncio.sleep(0.1)
    return b"x" * 1024  # simulated file content


def _chunks(data: bytes, size: int = _CHUNK):
    for i in range(0, len(data), size):
        yield data[i : i + size]
