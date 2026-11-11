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
    status: str = ""
    task_queue: str = ""
    start_time: str = ""
    close_time: str = ""
    execution_duration_ms: int = 0
    parent_workflow_id: str = ""
    memo: dict[str, str] = field(default_factory=dict)
    search_attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class AuditResult:
    total_entries: int
    namespaces_scanned: list[str]
    entries: list[AuditEntry] = field(default_factory=list)
