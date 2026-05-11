"""
Contracts for reusable WeCom group invite workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DuplicateNamePolicy(StrEnum):
    """How to resolve duplicate search results."""

    FIRST = "first"


class GroupInviteEntryMode(StrEnum):
    """How the workflow enters the group creation flow."""

    FROM_CUSTOMER_CHAT = "from_customer_chat"


@dataclass(frozen=True)
class GroupInviteRequest:
    """Input contract for a group invite workflow."""

    device_serial: str
    customer_name: str
    members: list[str]
    group_name: str = ""
    entry_mode: GroupInviteEntryMode = GroupInviteEntryMode.FROM_CUSTOMER_CHAT
    duplicate_name_policy: DuplicateNamePolicy = DuplicateNamePolicy.FIRST
    post_confirm_wait_seconds: float = 1.0
    send_message_before_create: bool = False
    pre_create_message_text: str = ""
    send_test_message: bool = True
    test_message_text: str = "测试"

    def normalized_members(self) -> list[str]:
        """Return trimmed, de-duplicated member names while preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for raw_member in self.members:
            member = raw_member.strip()
            if not member or member in seen:
                continue
            seen.add(member)
            result.append(member)
        return result


@dataclass
class GroupInviteResult:
    """Execution result for a group invite workflow."""

    success: bool
    customer_name: str
    group_name: str
    requested_members: list[str] = field(default_factory=list)
    selected_members: list[str] = field(default_factory=list)
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)
