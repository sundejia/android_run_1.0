"""
Legacy compatibility shim for the old backend blacklist service.

New code should import `BlacklistChecker` / `BlacklistWriter` from
`wecom_automation.services.blacklist_service` directly. This module remains only
so old imports keep working without reintroducing divergent blacklist logic.
"""

from __future__ import annotations

from typing import Optional

from wecom_automation.services.blacklist_service import BlacklistChecker, BlacklistWriter


class BlacklistService(BlacklistWriter):
    """Backward-compatible alias around the canonical blacklist implementation."""

    @classmethod
    def load_cache(cls) -> None:
        BlacklistChecker.load_cache()

    @classmethod
    def is_blacklisted(
        cls,
        device_serial: str,
        customer_name: str,
        customer_channel: Optional[str] = None,
        fail_closed: bool = False,
    ) -> bool:
        return BlacklistChecker.is_blacklisted(
            device_serial=device_serial,
            customer_name=customer_name,
            customer_channel=customer_channel,
            fail_closed=fail_closed,
        )

    @classmethod
    def invalidate_cache(cls) -> None:
        BlacklistChecker.invalidate_cache()


__all__ = ["BlacklistService"]
