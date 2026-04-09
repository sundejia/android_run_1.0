"""
Multi-frame AI review for video messages: extract 4 frames, upload each like images, persist on videos row.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.image_review_client import (
    REVIEW_STATUS_COMPLETED,
    REVIEW_STATUS_FAILED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_TIMEOUT,
    _broadcast_history_refresh_for_message_with_reason,
    analyze_local_image_file,
)
from services.video_frame_extract import extract_review_frames
from utils.path_utils import get_project_root

logger = logging.getLogger(__name__)

REVIEW_STATUS_PARTIAL = "partial"

_message_locks: dict[int, asyncio.Lock] = {}


def _lock_for(message_id: int) -> asyncio.Lock:
    if message_id not in _message_locks:
        _message_locks[message_id] = asyncio.Lock()
    return _message_locks[message_id]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persist_video_review(
    message_id: int,
    db_path: str | None,
    *,
    ai_review_score: float | None = None,
    ai_review_frames_json: str | None = None,
    ai_review_at: str | None = None,
    ai_review_status: str | None = None,
    ai_review_error: str | None = None,
    ai_review_requested_at: str | None = None,
) -> None:
    try:
        from wecom_automation.database.repository import ConversationRepository
        from wecom_automation.database.schema import get_db_path
    except ImportError:
        logger.debug("video_review_service: database modules unavailable, skip persist")
        return

    path = get_db_path(db_path)
    if not path.exists():
        logger.warning("video_review_service: database not found at %s, skip persist", path)
        return

    try:
        repo = ConversationRepository(str(path), auto_init=True)
        repo.update_video_review_by_message_id(
            message_id,
            ai_review_score=ai_review_score,
            ai_review_frames_json=ai_review_frames_json,
            ai_review_at=ai_review_at,
            ai_review_status=ai_review_status,
            ai_review_error=ai_review_error,
            ai_review_requested_at=ai_review_requested_at,
        )
    except Exception as exc:
        logger.warning("video_review_service: failed to persist review for message_id=%s: %s", message_id, exc)


async def _broadcast_video_review(message_id: int, db_path: str | None, status: str | None, score: float | None) -> None:
    extra: dict[str, Any] = {"video_review": True}
    if status:
        extra["video_review_status"] = status
    if score is not None:
        extra["video_review_score"] = score
    await _broadcast_history_refresh_for_message_with_reason(
        message_id,
        db_path,
        reason=f"video_review_{status}" if status else "video_review",
        extra=extra,
    )


def _resolve_video_file_path(file_path: str) -> Path | None:
    if not file_path or file_path.startswith("[not downloaded]"):
        return None
    p = Path(file_path).expanduser()
    if p.is_file():
        return p.resolve()
    root = get_project_root().resolve()
    candidate = (root / file_path).resolve()
    if candidate.is_file():
        return candidate
    return None


def _resolve_frame_path(relative_path: str) -> Path:
    p = Path(relative_path)
    if p.is_file():
        return p.resolve()
    return (get_project_root() / relative_path).resolve()


async def run_video_review_for_message(message_id: int, db_path: str | None = None) -> None:
    """
    Extract 4 frames from the video for this message, analyze each via image-rating-server,
    then store aggregate + per-frame JSON on the videos row.
    """
    from services.image_review_client import _get_runtime_settings

    async with _lock_for(message_id):
        enabled, _server_url, timeout_seconds = _get_runtime_settings(None)
        if not enabled:
            logger.info("video_review_service: image upload disabled, skip video review")
            return
        if not _server_url:
            logger.debug("video_review_service: image review server URL not configured")
            return

        try:
            from wecom_automation.database.repository import ConversationRepository
            from wecom_automation.database.schema import get_db_path
        except ImportError:
            logger.debug("video_review_service: database unavailable")
            return

        path = get_db_path(db_path)
        if not path.exists():
            return

        repo = ConversationRepository(str(path), auto_init=True)
        video = repo.get_video_for_message(message_id)
        if not video:
            return

        if video.ai_review_status == REVIEW_STATUS_COMPLETED:
            logger.debug("video_review_service: skip already completed message_id=%s", message_id)
            return

        video_file = _resolve_video_file_path(video.file_path)
        if not video_file:
            logger.info("video_review_service: no local video file for message_id=%s", message_id)
            return

        requested_at = _utc_now_iso()
        _persist_video_review(
            message_id,
            db_path,
            ai_review_status=REVIEW_STATUS_PENDING,
            ai_review_error="",
            ai_review_requested_at=requested_at,
        )
        await _broadcast_video_review(message_id, db_path, REVIEW_STATUS_PENDING, None)

        frames, err = extract_review_frames(
            video_file,
            message_id,
            duration_seconds=video.duration_seconds,
        )
        if err or not frames:
            _persist_video_review(
                message_id,
                db_path,
                ai_review_status=REVIEW_STATUS_FAILED,
                ai_review_error=err or "frame extraction failed",
                ai_review_requested_at=requested_at,
            )
            await _broadcast_video_review(message_id, db_path, REVIEW_STATUS_FAILED, None)
            return

        async def _one_frame(rel_path: str) -> dict[str, Any]:
            p = _resolve_frame_path(rel_path)
            res = await analyze_local_image_file(
                p,
                server_url=None,
                auto_analyze=True,
                timeout_seconds=timeout_seconds,
            )
            return {
                "ok": res.ok,
                "status": res.status,
                "image_id": res.image_id,
                "score": res.score,
                "details_json": res.details_json,
                "error": res.error,
            }

        frame_metas = [
            {
                "frame_index": f.frame_index,
                "percent": f.percent,
                "time_seconds": f.time_seconds,
                "file_path": f.relative_path,
            }
            for f in frames
        ]

        analyses = await asyncio.gather(
            *[_one_frame(f.relative_path) for f in frames],
            return_exceptions=True,
        )

        combined: list[dict[str, Any]] = []
        scores_ok: list[float] = []
        any_completed = False
        all_failed = True

        for meta, an in zip(frame_metas, analyses, strict=True):
            row: dict[str, Any] = dict(meta)
            if isinstance(an, BaseException):
                row["ai_review_status"] = REVIEW_STATUS_FAILED
                row["ai_review_error"] = str(an)
                row["review_external_id"] = None
                row["ai_review_score"] = None
                row["ai_review_details_json"] = None
            else:
                row["review_external_id"] = an.get("image_id")
                row["ai_review_score"] = an.get("score")
                row["ai_review_details_json"] = an.get("details_json")
                row["ai_review_status"] = an.get("status")
                row["ai_review_error"] = an.get("error") or ""
                st = an.get("status")
                if st == REVIEW_STATUS_COMPLETED and an.get("score") is not None:
                    try:
                        scores_ok.append(float(an["score"]))
                    except (TypeError, ValueError):
                        pass
                    any_completed = True
                    all_failed = False
                elif st == REVIEW_STATUS_TIMEOUT:
                    all_failed = False
                elif an.get("ok"):
                    all_failed = False
            combined.append(row)

        avg: float | None = None
        if scores_ok:
            avg = sum(scores_ok) / len(scores_ok)

        if all_failed:
            final_status = REVIEW_STATUS_FAILED
            final_err = "All frame reviews failed"
        elif any_completed and len(scores_ok) < len(frames):
            final_status = REVIEW_STATUS_PARTIAL
            final_err = ""
        elif any_completed:
            final_status = REVIEW_STATUS_COMPLETED
            final_err = ""
        else:
            final_status = REVIEW_STATUS_FAILED
            final_err = "No frame returned a completed score"

        frames_json = json.dumps(combined, ensure_ascii=False)
        analyzed_at = _utc_now_iso() if any_completed else None

        _persist_video_review(
            message_id,
            db_path,
            ai_review_score=avg,
            ai_review_frames_json=frames_json,
            ai_review_at=analyzed_at,
            ai_review_status=final_status,
            ai_review_error=final_err,
            ai_review_requested_at=requested_at,
        )
        await _broadcast_video_review(message_id, db_path, final_status, avg)


def schedule_video_review_for_message(message_id: int, db_path: str | None = None) -> None:
    """Fire-and-forget when an asyncio loop is running (same pattern as image review)."""
    try:
        import asyncio

        asyncio.ensure_future(run_video_review_for_message(message_id, db_path))
    except Exception as exc:
        logger.warning(
            "video_review_service: could not schedule review for message_id=%s: %s",
            message_id,
            exc,
        )
