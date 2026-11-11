from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PoolConfig:
    """Input to start a CredentialPoolWorkflow."""
    pool_name: str
    credential_names: list[str]
    lock_timeout_seconds: int = 300


@dataclass
class CredentialInfo:
    name: str
    username: str
    password: str


@dataclass
class PoolEntry:
    credential_name: str
    holder_workflow_id: str = ""
    acquired_at: str = ""

    @property
    def is_locked(self) -> bool:
        return bool(self.holder_workflow_id)


@dataclass
class WaitingRequest:
    requester_workflow_id: str
    requested_at: str = ""


@dataclass
class PoolStatus:
    pool_name: str
    credentials: list[PoolEntry] = field(default_factory=list)
    queue: list[str] = field(default_factory=list)
    total_acquires: int = 0
    total_releases: int = 0


# ── Signal / child-workflow payloads ─────────────────────────

@dataclass
class AcquireFromPoolInput:
    """Input for AcquireCredentialWorkflow (child workflow)."""
    pool_name: str
    timeout_seconds: int = 300


@dataclass
class AcquireSignal:
    """Signal sent to the pool to request any available credential."""
    requester_workflow_id: str


@dataclass
class ReleaseSignal:
    """Signal sent to the pool to release a specific credential."""
    requester_workflow_id: str
    credential_name: str


@dataclass
class GrantedSignal:
    """Signal sent back to the requester with the credential."""
    credential_name: str
    username: str
    password: str
