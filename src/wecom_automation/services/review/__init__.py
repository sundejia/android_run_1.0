"""Review-gating subsystem.

Bridges the image-rating-server's review verdict to the existing
MediaEventBus / AutoGroupInviteAction pipeline.

Public surface:
- contracts: ReviewVerdict / WebhookEnvelope / approval rule (mirrors rating-server)
"""
from wecom_automation.services.review.contracts import (
    DECISION_FAIL,
    DECISION_PASS,
    IMAGE_REVIEW_COMPLETED_EVENT,
    ReviewVerdict,
    WebhookEnvelope,
    is_approved,
    parse_envelope,
)

__all__ = [
    "DECISION_FAIL",
    "DECISION_PASS",
    "IMAGE_REVIEW_COMPLETED_EVENT",
    "ReviewVerdict",
    "WebhookEnvelope",
    "is_approved",
    "parse_envelope",
]
