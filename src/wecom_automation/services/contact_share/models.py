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
    send_message_before_share: bool = False
    pre_share_message_text: str = ""
    assume_current_chat: bool = False
    # If pre-share message is sent but card delivery fails afterwards, send this
    # text as a recovery so the customer is not left with a half-promise like
    # "this is the card" without an actual card. Empty disables recovery.
    recovery_message_on_failure_text: str = (
        "抱歉，系统稍后会自动重新发送名片，您也可以稍等老师手动发送，给您带来不便十分抱歉~"
    )


@dataclass
class ContactShareResult:
    """Result of a contact card sharing attempt."""

    success: bool
    customer_name: str
    contact_name: str
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)
