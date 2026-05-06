"""
Shared portrait/decision gate evaluator for media auto-actions.

Reads the persisted image-rating-server review result for a given media
message (image or video) and decides whether the customer's media passes
the configured gate. Both ``AutoGroupInviteAction`` and
``AutoBlacklistAction`` consume the same evaluator so they always agree
on a single verdict per (message, scan-cycle).

Gate rule:

* ``review_gate.enabled = False`` -> ``gate_pass = is_portrait == True``
* ``review_gate.enabled = True``  -> ``gate_pass = is_portrait and decision == "合格"``

For videos (multi-frame review), each frame is evaluated independently
with the same per-frame rule and the gate passes when at least
``ceil(N * video_pass_ratio)`` frames pass (default >= 50%).

When the underlying review row is missing or the JSON cannot be parsed
we report ``has_data=False`` so callers can decide to skip the action,
log a WARNING and fall back to AI reply.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DECISION_PASS = "合格"

REVIEW_STATUS_COMPLETED = "completed"
REVIEW_STATUS_PARTIAL = "partial"


@dataclass
class MediaReviewDecision:
    """Outcome of evaluating a media message against the portrait/decision gate."""

    gate_pass: bool = False
    has_data: bool = False
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _coerce_bool(value: Any) -> bool | None:
    """Coerce common JSON shapes for booleans; return None when unknown."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "y", "1", "是", "真"}:
            return True
        if v in {"false", "no", "n", "0", "否", "假"}:
            return False
    return None


def _parse_details_json(raw: str | None) -> dict[str, Any] | None:
    """Parse ai_review_details_json into a dict; tolerate malformed input."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _extract_portrait_and_decision(details: dict[str, Any]) -> tuple[bool | None, str | None]:
    """Pull is_portrait + decision from a parsed details payload.

    Persisted ``ai_review_details_json`` mirrors the analyzer return value;
    the gate-relevant fields live under ``result``.
    """
    nested = details.get("result")
    if not isinstance(nested, dict):
        return None, None

    portrait = _coerce_bool(nested.get("is_portrait"))

    decision_raw = nested.get("decision")
    decision = str(decision_raw).strip() if isinstance(decision_raw, str) else None
    return portrait, decision


def _frame_gate_pass(
    portrait: bool | None,
    decision: str | None,
    *,
    gate_enabled: bool,
) -> bool:
    """Apply the per-frame / per-image rule."""
    if portrait is not True:
        return False
    if gate_enabled and decision != DECISION_PASS:
        return False
    return True


def _evaluate_image(
    db_path: str,
    message_id: int,
    *,
    gate_enabled: bool,
) -> MediaReviewDecision:
    try:
        from wecom_automation.database.repository import ConversationRepository
    except ImportError as exc:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason=f"repository_unavailable: {exc}",
        )

    try:
        repo = ConversationRepository(db_path, auto_init=False)
        image = repo.get_image_for_message(message_id)
    except Exception as exc:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason=f"image_lookup_failed: {exc}",
        )

    if image is None:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="image_row_missing",
            details={"message_id": message_id},
        )

    if image.ai_review_status != REVIEW_STATUS_COMPLETED:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason=f"ai_review_status={image.ai_review_status!r}",
            details={
                "message_id": message_id,
                "ai_review_status": image.ai_review_status,
                "ai_review_error": image.ai_review_error,
            },
        )

    parsed = _parse_details_json(image.ai_review_details_json)
    if parsed is None:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="details_json_unparsable",
            details={"message_id": message_id},
        )

    portrait, decision_from_details = _extract_portrait_and_decision(parsed)
    decision = decision_from_details or image.ai_review_decision

    detail_log: dict[str, Any] = {
        "message_id": message_id,
        "is_portrait": portrait,
        "decision": decision,
        "gate_enabled": gate_enabled,
    }

    if portrait is None:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="is_portrait_missing",
            details=detail_log,
        )

    gate_pass = _frame_gate_pass(portrait, decision, gate_enabled=gate_enabled)
    if gate_pass:
        return MediaReviewDecision(
            gate_pass=True,
            has_data=True,
            reason="ok",
            details=detail_log,
        )

    if portrait is not True:
        reason = "portrait_false"
    else:
        reason = "decision_not_qualified"
    return MediaReviewDecision(
        gate_pass=False,
        has_data=True,
        reason=reason,
        details=detail_log,
    )


def _evaluate_video(
    db_path: str,
    message_id: int,
    *,
    gate_enabled: bool,
    video_pass_ratio: float,
) -> MediaReviewDecision:
    try:
        from wecom_automation.database.repository import ConversationRepository
    except ImportError as exc:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason=f"repository_unavailable: {exc}",
        )

    try:
        repo = ConversationRepository(db_path, auto_init=False)
        video = repo.get_video_for_message(message_id)
    except Exception as exc:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason=f"video_lookup_failed: {exc}",
        )

    if video is None:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="video_row_missing",
            details={"message_id": message_id},
        )

    if video.ai_review_status not in (REVIEW_STATUS_COMPLETED, REVIEW_STATUS_PARTIAL):
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason=f"ai_review_status={video.ai_review_status!r}",
            details={
                "message_id": message_id,
                "ai_review_status": video.ai_review_status,
                "ai_review_error": video.ai_review_error,
            },
        )

    raw_frames = video.ai_review_frames_json
    if not raw_frames:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="frames_json_missing",
            details={"message_id": message_id},
        )

    try:
        frames = json.loads(raw_frames)
    except (TypeError, ValueError):
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="frames_json_unparsable",
            details={"message_id": message_id},
        )

    if not isinstance(frames, list) or not frames:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="frames_empty",
            details={"message_id": message_id},
        )

    total = len(frames)
    passed = 0
    parsed_any = False
    per_frame: list[dict[str, Any]] = []

    for entry in frames:
        if not isinstance(entry, dict):
            per_frame.append({"ok": False, "reason": "non_dict_frame"})
            continue
        details = _parse_details_json(entry.get("ai_review_details_json"))
        if details is None:
            per_frame.append(
                {
                    "frame_index": entry.get("frame_index"),
                    "ok": False,
                    "reason": "details_json_unparsable",
                }
            )
            continue
        parsed_any = True
        portrait, decision = _extract_portrait_and_decision(details)
        ok = _frame_gate_pass(portrait, decision, gate_enabled=gate_enabled)
        if ok:
            passed += 1
        per_frame.append(
            {
                "frame_index": entry.get("frame_index"),
                "is_portrait": portrait,
                "decision": decision,
                "ok": ok,
            }
        )

    if not parsed_any:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="no_parseable_frames",
            details={
                "message_id": message_id,
                "frames": per_frame,
                "total": total,
            },
        )

    threshold = max(1, math.ceil(total * video_pass_ratio))
    detail_log = {
        "message_id": message_id,
        "passed_frames": passed,
        "total_frames": total,
        "threshold": threshold,
        "gate_enabled": gate_enabled,
        "frames": per_frame,
    }

    if passed >= threshold:
        return MediaReviewDecision(
            gate_pass=True,
            has_data=True,
            reason="ok",
            details=detail_log,
        )

    return MediaReviewDecision(
        gate_pass=False,
        has_data=True,
        reason="video_passed_below_threshold",
        details=detail_log,
    )


def evaluate_gate_pass(
    *,
    message_id: int | None,
    message_type: str,
    db_path: str | None,
    gate_enabled: bool,
    video_pass_ratio: float = 0.5,
) -> MediaReviewDecision:
    """Evaluate the portrait/decision gate for a single media message.

    Args:
        message_id: Local DB id of the media message. ``None`` is treated as
            missing data (the caller decides whether to fall back).
        message_type: ``"image"`` or ``"video"``. Anything else returns
            ``has_data=False`` because the gate only governs media events.
        db_path: Conversation SQLite path (must contain ``images`` /
            ``videos`` rows).  ``None`` skips the gate altogether and
            returns ``has_data=False`` so legacy callers (no DB wired in)
            keep their existing behaviour.
        gate_enabled: ``review_gate.enabled`` setting.  Picks the rule.
        video_pass_ratio: Minimum fraction of frames that must pass for
            video media. Defaults to 0.5 (i.e. >= ceil(N/2)).
    """
    if db_path is None:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="db_path_not_configured",
        )
    if message_id is None:
        return MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="message_id_missing",
        )

    if message_type == "image":
        return _evaluate_image(db_path, message_id, gate_enabled=gate_enabled)
    if message_type == "video":
        return _evaluate_video(
            db_path,
            message_id,
            gate_enabled=gate_enabled,
            video_pass_ratio=video_pass_ratio,
        )

    return MediaReviewDecision(
        gate_pass=False,
        has_data=False,
        reason=f"unsupported_message_type: {message_type}",
    )
