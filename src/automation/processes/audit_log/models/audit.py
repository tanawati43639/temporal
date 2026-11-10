from dataclasses import dataclass, field


@dataclass
class AuditInput:
    lookback_days: int
    namespace_filter: list[str] | None = None


@dataclass
class ScanNamespaceInput:
    namespace: str
    lookback_days: int


@dataclass
class AuditEntry:
    workflow_id: str
    run_id: str
    workflow_type: str
    namespace: str
    event_type: str
    identity: str
    timestamp: str


@dataclass
class AuditResult:
    total_entries: int
    namespaces_scanned: list[str]
    entries: list[AuditEntry] = field(default_factory=list)
