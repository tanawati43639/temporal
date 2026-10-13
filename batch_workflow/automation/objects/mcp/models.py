"""Data models for MCP session activities."""

from dataclasses import dataclass


@dataclass
class SessionInfo:
    task_queue: str


@dataclass
class ToolInput:
    tool_name: str
    args: dict


@dataclass
class ToolOutput:
    result: dict
