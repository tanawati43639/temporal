"""Data models for the notify process and its objects (email / sharepoint)."""

from dataclasses import dataclass


@dataclass
class EmailInput:
    to: str
    subject: str
    body: str
    # Makes retries safe: the activity skips sending if this key was already sent.
    idempotency_key: str


@dataclass
class UploadInput:
    site: str
    folder: str
    filename: str
    # A URL/pointer to the content, NOT the bytes — keeps large files out of
    # Event History (2 MB payload limit).
    source_ref: str


@dataclass
class NotifyInput:
    recipient: str
    report_name: str
    report_ref: str
