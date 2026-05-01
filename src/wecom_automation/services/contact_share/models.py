"""
Data models for the contact card sharing workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContactShareRequest:
    """Request to share a contact card with a customer."""

    device_serial: str
    customer_name: str
    contact_name: str
    kefu_name: str = ""


@dataclass
class ContactShareResult:
    """Result of a contact card sharing attempt."""

    success: bool
    customer_name: str
    contact_name: str
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)
