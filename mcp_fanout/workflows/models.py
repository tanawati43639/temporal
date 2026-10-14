from dataclasses import dataclass, field


@dataclass
class ToolInput:
    tool_name: str
    args: dict = field(default_factory=dict)


@dataclass
class ApiInput:
    endpoint: str
    body: dict = field(default_factory=dict)


@dataclass
class ToolOutput:
    result: dict = field(default_factory=dict)


@dataclass
class DepartmentInput:
    department_id: str
    customer_ids: list[str] = field(default_factory=list)


@dataclass
class FanoutInput:
    departments: list[DepartmentInput] = field(default_factory=list)


@dataclass
class CustomerResult:
    customer_id: str
    profile: dict = field(default_factory=dict)
    notification: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class DepartmentResult:
    department_id: str
    customers: list[CustomerResult] = field(default_factory=list)
    error: str | None = None
