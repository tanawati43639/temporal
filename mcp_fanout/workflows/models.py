from dataclasses import dataclass, field


@dataclass
class ToolInput:
    tool_name: str
    args: dict = field(default_factory=dict)


@dataclass
class ToolOutput:
    result: dict = field(default_factory=dict)


@dataclass
class FanoutInput:
    customer_ids: list[str] = field(default_factory=list)


@dataclass
class CustomerResult:
    customer_id: str
    profile: dict = field(default_factory=dict)
    notification: dict = field(default_factory=dict)
    error: str | None = None
