from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AcquireRequest:
    requester_workflow_id: str
    credential_name: str
    timeout_seconds: int = 300


@dataclass
class ReleaseRequest:
    requester_workflow_id: str


@dataclass
class LockEntry:
    workflow_id: str
    acquired_at: str = ""


@dataclass
class LockStatus:
    credential_name: str
    holder: LockEntry | None = None
    queue: list[str] = field(default_factory=list)
    total_acquires: int = 0
    total_releases: int = 0


@dataclass
class CredentialInfo:
    name: str
    username: str
    password: str


@dataclass
class GrantedSignal:
    credential_name: str
    username: str
    password: str


@dataclass
class LockManagerInput:
    credential_name: str
    lock_timeout_seconds: int = 300
