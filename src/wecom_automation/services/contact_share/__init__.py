"""Contact card sharing service for WeCom automation."""

from wecom_automation.services.contact_share.models import (
    ContactShareRequest,
    ContactShareResult,
)
from wecom_automation.services.contact_share.service import (
    ContactShareService,
    IContactShareService,
)

__all__ = [
    "ContactShareRequest",
    "ContactShareResult",
    "ContactShareService",
    "IContactShareService",
]
