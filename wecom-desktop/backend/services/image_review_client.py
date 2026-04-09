"""
Image review upload client.

Uploads local images to the image-rating-server, waits for AI analysis with a
configurable timeout, persists state into the local database, and broadcasts a
global Sidecar history refresh when the review state changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/api/v1/upload"
ANALYSIS_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_REVIEW_TIMEOUT_SECONDS = 40

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_COMPLETED = "completed"
REVIEW_STATUS_TIMEOUT = "timeout"
REVIEW_STATUS_FAILED = "failed"


@dataclass
class LocalImageReviewResult:
    """Outcome of uploading a local file to the rating server and optionally waiting for analysis."""

    ok: bool
    image_id: str | None = None
    score: float | None = None
    model: str | None = None
    decision: str | None = None
    details_json: str | None = None
    analyzed_at: str | None = None
    status: str = REVIEW_STATUS_FAILED
    error: str | None = None


_uploaded_paths: set[str] = set()
_inflight_uploads: dict[str, asyncio.Task[bool]] = {}


def _utc_now_iso() -> str:
    """Return an ISO timestamp with timezone information."""
    return datetime.now(timezone.utc).isoformat()


def _guess_mime(path: Path) -> str:
    """Return a best-effort MIME type from file suffix."""
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(path.suffix.lower(), "application/octet-stream")


def _pick_upload_result(body: dict[str, Any], filename: str) -> tuple[str | None, bool, bool]:
    """
    Pick the uploaded image_id from the rating-server response.

    Returns:
        (image_id, is_success_status, any_result_matched)
    """
    results = body.get("results") or []
    if not results:
        return None, False, False

    filename_only = Path(filename).name
    chosen: dict[str, Any] | None = None
    for result in results:
        original_filename = result.get("original_filename") or ""
        if original_filename == filename_only or original_filename == filename:
            chosen = result
            break

    if chosen is None:
        chosen = results[0]

    metadata = chosen.get("metadata") or {}
    image_id = metadata.get("image_id")
    if not image_id:
        return None, False, True

    status = str(chosen.get("status") or "").lower()
    return str(image_id), status == "success", True


def _get_runtime_settings(server_url: str | None) -> tuple[bool, str, int, bool]:
    """Resolve feature toggle, server URL and timeout from settings when available."""
    enabled = True
    resolved_server_url = (server_url or "").strip()
    timeout_seconds = DEFAULT_REVIEW_TIMEOUT_SECONDS
    low_spec_mode = False

    try:
        from services.settings import get_settings_service

        service = get_settings_service()
        enabled = bool(service.is_image_upload_enabled())
        if not resolved_server_url:
            resolved_server_url = str(service.get_image_server_ip() or "").strip()
        timeout_seconds = service.get_image_review_timeout_seconds()
        low_spec_mode = service.is_low_spec_mode()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("image_review_client: settings unavailable, using fallback defaults: %s", exc)

    try:
        timeout_seconds = max(1, int(timeout_seconds))
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_REVIEW_TIMEOUT_SECONDS

    return enabled, resolved_server_url.rstrip("/"), timeout_seconds, low_spec_mode


def _persist_review_to_local_db(
    message_id: int,
    db_path: str | None,
    *,
    review_external_id: str | None = None,
    ai_review_score: float | None = None,
    ai_review_model: str | None = None,
    ai_review_decision: str | None = None,
    ai_review_details_json: str | None = None,
    ai_review_at: str | None = None,
    ai_review_status: str | None = None,
    ai_review_error: str | None = None,
    ai_review_requested_at: str | None = None,
) -> None:
    """Persist image review fields onto the local images row for a message."""
    try:
        from wecom_automation.database.repository import ConversationRepository
        from wecom_automation.database.schema import get_db_path
    except ImportError:
        logger.debug("image_review_client: database modules unavailable, skip persist")
        return

    path = get_db_path(db_path)
    if not path.exists():
        logger.warning("image_review_client: database not found at %s, skip review persist", path)
        return

    try:
        repo = ConversationRepository(str(path), auto_init=True)
        repo.update_image_review_by_message_id(
            message_id,
            review_external_id=review_external_id,
            ai_review_score=ai_review_score,
            ai_review_model=ai_review_model,
            ai_review_decision=ai_review_decision,
            ai_review_details_json=ai_review_details_json,
            ai_review_at=ai_review_at,
            ai_review_status=ai_review_status,
            ai_review_error=ai_review_error,
            ai_review_requested_at=ai_review_requested_at,
        )
    except Exception as exc:
        logger.warning(
            "image_review_client: failed to persist review for message_id=%s: %s",
            message_id,
            exc,
        )


def _get_review_context(message_id: int, db_path: str | None) -> dict[str, Any] | None:
    """Resolve customer context for a message so Sidecar can refresh the right conversation."""
    try:
        from wecom_automation.database.repository import ConversationRepository
        from wecom_automation.database.schema import get_db_path
    except ImportError:
        return None

    path = get_db_path(db_path)
    if not path.exists():
        return None

    try:
        repo = ConversationRepository(str(path), auto_init=True)
        return repo.get_message_review_context(message_id)
    except Exception as exc:
        logger.warning(
            "image_review_client: failed to resolve message review context for message_id=%s: %s",
            message_id,
            exc,
        )
        return None


async def _broadcast_history_refresh_for_message(message_id: int, db_path: str | None) -> None:
    """Broadcast a global history refresh for the message's conversation."""
    await _broadcast_history_refresh_for_message_with_reason(message_id, db_path, reason=None)


async def _broadcast_history_refresh_for_message_with_reason(
    message_id: int,
    db_path: str | None,
    *,
    reason: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Broadcast a global history refresh for the message's conversation."""
    try:
        from routers.global_websocket import broadcast_history_refresh
    except ImportError:
        logger.debug("image_review_client: global websocket module unavailable, skip broadcast")
        return

    context = _get_review_context(message_id, db_path)
    if not context:
        logger.debug("image_review_client: no review context found for message_id=%s", message_id)
        return

    customer_name = context.get("customer_name")
    if not customer_name:
        return

    try:
        await broadcast_history_refresh(
            customer_name=customer_name,
            channel=context.get("channel"),
            customer_id=context.get("customer_id"),
            reason=reason,
            extra={
                "message_id": message_id,
                "device_serial": context.get("device_serial"),
                **(extra or {}),
            },
        )
    except Exception as exc:
        logger.warning(
            "image_review_client: failed to broadcast history refresh for message_id=%s: %s",
            message_id,
            exc,
        )


def _parse_analysis_payload(analysis: dict[str, Any]) -> tuple[float | None, str | None, str | None, str | None]:
    """Extract the fields we persist from an analysis payload."""
    score: float | None = None
    score_value = analysis.get("score")
    if score_value is not None:
        try:
            score = float(score_value)
        except (TypeError, ValueError):
            score = None

    model_value = analysis.get("model")
    model = str(model_value) if model_value is not None else None

    created_at = analysis.get("created_at")
    analyzed_at = created_at if isinstance(created_at, str) and created_at.strip() else None

    details_json: str | None = None
    details = analysis.get("details")
    if details is not None:
        try:
            details_json = json.dumps(details, ensure_ascii=False)
        except (TypeError, ValueError):
            details_json = None

    return score, model, details_json, analyzed_at


async def _poll_analysis_until_ready(
    client: Any,
    base_url: str,
    image_id: str,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    """Poll the analysis endpoint until the review is ready or the timeout is reached."""
    analysis_url = f"{base_url}/api/v1/images/{image_id}/analysis"
    deadline = time.monotonic() + timeout_seconds

    while True:
        response = await client.get(analysis_url)
        if response.status_code == 200:
            return response.json()

        if response.status_code != 404:
            raise RuntimeError(
                f"Unexpected analysis response HTTP {response.status_code}: {response.text[:300]}"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None

        await asyncio.sleep(min(ANALYSIS_POLL_INTERVAL_SECONDS, remaining))


async def _poll_image_detail_until_ready(
    client: Any,
    base_url: str,
    image_id: str,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    """Poll the image detail endpoint until score/decision metadata is present."""
    detail_url = f"{base_url}/api/v1/images/{image_id}"
    deadline = time.monotonic() + timeout_seconds

    while True:
        response = await client.get(detail_url)
        if response.status_code == 200:
            payload = response.json()
            if any(
                payload.get(key) is not None
                for key in ("ai_score", "ai_decision", "ai_analyzed_at")
            ):
                return payload
        elif response.status_code != 404:
            raise RuntimeError(
                f"Unexpected image detail response HTTP {response.status_code}: {response.text[:300]}"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None

        await asyncio.sleep(min(ANALYSIS_POLL_INTERVAL_SECONDS, remaining))


async def _fetch_ai_decision(client: Any, base_url: str, image_id: str) -> str | None:
    """Fetch the image detail record so we can persist ai_decision when available."""
    response = await client.get(f"{base_url}/api/v1/images/{image_id}")
    if response.status_code != 200:
        return None

    data = response.json()
    decision = data.get("ai_decision")
    return str(decision) if decision is not None else None


async def analyze_local_image_file(
    image_path: str | Path,
    *,
    server_url: str | None = None,
    auto_analyze: bool = True,
    timeout_seconds: int | None = None,
) -> LocalImageReviewResult:
    """
    Upload a local image to the rating server and optionally wait for analysis.

    Does not read or write the local SQLite database (use for video frame batches, etc.).
    """
    try:
        import httpx
    except ImportError:
        return LocalImageReviewResult(ok=False, error="httpx is not installed", status=REVIEW_STATUS_FAILED)

    enabled, resolved_server_url, default_timeout, _ = _get_runtime_settings(server_url)
    effective_timeout = default_timeout if timeout_seconds is None else max(1, int(timeout_seconds))

    if not enabled:
        return LocalImageReviewResult(
            ok=False,
            error="Image review upload disabled",
            status=REVIEW_STATUS_FAILED,
        )
    if not resolved_server_url:
        return LocalImageReviewResult(
            ok=False,
            error="Image review server URL not configured",
            status=REVIEW_STATUS_FAILED,
        )

    image_file = Path(image_path).expanduser().resolve()
    if not image_file.is_file():
        return LocalImageReviewResult(
            ok=False,
            error=f"Local image does not exist: {image_file}",
            status=REVIEW_STATUS_FAILED,
        )

    upload_url = f"{resolved_server_url}{UPLOAD_PATH}"
    image_id: str | None = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            with image_file.open("rb") as handle:
                response = await client.post(
                    upload_url,
                    files={"images": (image_file.name, handle, _guess_mime(image_file))},
                    data={"auto_analyze": "true" if auto_analyze else "false"},
                )

            if response.status_code not in (200, 201):
                return LocalImageReviewResult(
                    ok=False,
                    error=f"Upload failed with HTTP {response.status_code}: {response.text[:500]}",
                    status=REVIEW_STATUS_FAILED,
                )

            body = response.json()
            image_id, _, matched = _pick_upload_result(body, image_file.name)
            if not matched or not image_id:
                return LocalImageReviewResult(
                    ok=False,
                    error="Upload succeeded but image_id was not returned by review server",
                    status=REVIEW_STATUS_FAILED,
                )

            if not auto_analyze:
                return LocalImageReviewResult(
                    ok=True,
                    image_id=image_id,
                    status=REVIEW_STATUS_PENDING,
                )

            detail = await _poll_image_detail_until_ready(
                client, resolved_server_url, image_id, effective_timeout
            )
            if detail is None:
                return LocalImageReviewResult(
                    ok=False,
                    image_id=image_id,
                    status=REVIEW_STATUS_TIMEOUT,
                    error=f"Timed out waiting for image review result after {effective_timeout}s",
                )

            analysis = await _poll_analysis_until_ready(client, resolved_server_url, image_id, 5)
            decision = (
                str(detail.get("ai_decision"))
                if detail.get("ai_decision") is not None
                else await _fetch_ai_decision(client, resolved_server_url, image_id)
            )
            score, model, details_json, analyzed_at = _parse_analysis_payload(analysis or detail)

            if score is None:
                score_value = detail.get("ai_score")
                if score_value is not None:
                    try:
                        score = float(score_value)
                    except (TypeError, ValueError):
                        score = None

            if analyzed_at is None:
                analyzed_raw = detail.get("ai_analyzed_at")
                analyzed_at = str(analyzed_raw) if analyzed_raw is not None else None

            return LocalImageReviewResult(
                ok=True,
                image_id=image_id,
                score=score,
                model=model,
                decision=decision,
                details_json=details_json,
                analyzed_at=analyzed_at,
                status=REVIEW_STATUS_COMPLETED,
            )

    except Exception as exc:
        logger.exception("image_review_client: analyze_local_image_file failed for %s", image_path)
        return LocalImageReviewResult(
            ok=False,
            image_id=image_id,
            status=REVIEW_STATUS_FAILED,
            error=str(exc),
        )


async def _set_review_state(
    message_id: int,
    db_path: str | None,
    *,
    review_external_id: str | None = None,
    ai_review_score: float | None = None,
    ai_review_model: str | None = None,
    ai_review_decision: str | None = None,
    ai_review_details_json: str | None = None,
    ai_review_at: str | None = None,
    ai_review_status: str | None = None,
    ai_review_error: str | None = None,
    ai_review_requested_at: str | None = None,
    broadcast: bool = True,
) -> None:
    """Persist the review state, then optionally broadcast a Sidecar refresh."""
    _persist_review_to_local_db(
        message_id,
        db_path,
        review_external_id=review_external_id,
        ai_review_score=ai_review_score,
        ai_review_model=ai_review_model,
        ai_review_decision=ai_review_decision,
        ai_review_details_json=ai_review_details_json,
        ai_review_at=ai_review_at,
        ai_review_status=ai_review_status,
        ai_review_error=ai_review_error,
        ai_review_requested_at=ai_review_requested_at,
    )

    if broadcast:
        reason = None
        extra: dict[str, Any] = {}
        if ai_review_status:
            reason = f"image_review_{ai_review_status}"
            extra["review_status"] = ai_review_status
        if ai_review_score is not None:
            extra["review_score"] = ai_review_score
        if review_external_id:
            extra["review_external_id"] = review_external_id

        await _broadcast_history_refresh_for_message_with_reason(
            message_id,
            db_path,
            reason=reason,
            extra=extra or None,
        )


async def _upload_image_for_review_impl(
    image_path: str | Path,
    server_url: str | None,
    auto_analyze: bool,
    local_message_id: int | None,
    db_path: str | None,
    abs_path_key: str,
) -> bool:
    """Internal implementation for upload and review waiting."""
    enabled, resolved_server_url, timeout_seconds, _ = _get_runtime_settings(server_url)
    if not enabled:
        logger.info("image_review_client: upload feature disabled, skip image review")
        return False
    if not resolved_server_url:
        logger.debug("image_review_client: image review server URL not configured")
        return False

    image_file = Path(image_path).expanduser().resolve()
    if not image_file.is_file():
        logger.warning("image_review_client: local image does not exist: %s", image_file)
        return False

    review_requested_at = _utc_now_iso()
    if local_message_id:
        await _set_review_state(
            local_message_id,
            db_path,
            ai_review_status=REVIEW_STATUS_PENDING,
            ai_review_error="",
            ai_review_requested_at=review_requested_at,
            broadcast=False,
        )

    upload_url = f"{resolved_server_url}{UPLOAD_PATH}"
    logger.info(
        "image_review_client: uploading image file=%s target=%s auto_analyze=%s timeout=%ss",
        image_file.name,
        upload_url,
        auto_analyze,
        timeout_seconds,
    )

    result = await analyze_local_image_file(
        image_path,
        server_url=server_url,
        auto_analyze=auto_analyze,
        timeout_seconds=timeout_seconds,
    )

    if result.image_id is not None:
        _uploaded_paths.add(abs_path_key)

    if not local_message_id:
        if not auto_analyze:
            return result.ok
        return result.ok and result.status == REVIEW_STATUS_COMPLETED

    if not auto_analyze and result.ok:
        logger.info("image_review_client: auto_analyze disabled; upload finished without waiting for analysis")
        await _set_review_state(
            local_message_id,
            db_path,
            review_external_id=result.image_id,
            ai_review_status=REVIEW_STATUS_PENDING,
            ai_review_error="",
            ai_review_requested_at=review_requested_at,
        )
        return True

    if result.status == REVIEW_STATUS_TIMEOUT:
        logger.warning(
            "image_review_client: review timeout image_id=%s message_id=%s",
            result.image_id,
            local_message_id,
        )
        await _set_review_state(
            local_message_id,
            db_path,
            review_external_id=result.image_id,
            ai_review_status=REVIEW_STATUS_TIMEOUT,
            ai_review_error=result.error or "timeout",
            ai_review_requested_at=review_requested_at,
        )
        return False

    if not result.ok:
        await _set_review_state(
            local_message_id,
            db_path,
            review_external_id=result.image_id,
            ai_review_status=REVIEW_STATUS_FAILED,
            ai_review_error=result.error or "failed",
            ai_review_requested_at=review_requested_at,
        )
        return False

    await _set_review_state(
        local_message_id,
        db_path,
        review_external_id=result.image_id,
        ai_review_score=result.score,
        ai_review_model=result.model,
        ai_review_decision=result.decision,
        ai_review_details_json=result.details_json,
        ai_review_at=result.analyzed_at,
        ai_review_status=REVIEW_STATUS_COMPLETED,
        ai_review_error="",
        ai_review_requested_at=review_requested_at,
    )

    logger.info(
        "image_review_client: review completed image_id=%s message_id=%s score=%s decision=%s",
        result.image_id,
        local_message_id,
        result.score,
        result.decision,
    )
    return True


async def upload_image_for_review(
    image_path: str | Path,
    server_url: str | None = None,
    auto_analyze: bool = True,
    local_message_id: int | None = None,
    db_path: str | None = None,
) -> bool:
    """
    Upload a local image and wait for review completion with timeout.

    The function deduplicates both completed uploads and in-flight uploads for
    the same absolute file path within the current process.
    """
    resolved_path = str(Path(image_path).expanduser().resolve())

    if resolved_path in _uploaded_paths:
        logger.info("image_review_client: skip duplicate upload for %s", resolved_path)
        return True

    inflight = _inflight_uploads.get(resolved_path)
    if inflight is not None:
        logger.debug("image_review_client: waiting on in-flight upload for %s", resolved_path)
        return await inflight

    enabled, _, _, low_spec_mode = _get_runtime_settings(server_url)
    task = asyncio.create_task(
        _upload_image_for_review_impl(
            image_path=image_path,
            server_url=server_url,
            auto_analyze=auto_analyze,
            local_message_id=local_message_id,
            db_path=db_path,
            abs_path_key=resolved_path,
        )
    )
    _inflight_uploads[resolved_path] = task

    def _cleanup_inflight(completed_task: asyncio.Task[bool]) -> None:
        current = _inflight_uploads.get(resolved_path)
        if current is completed_task:
            _inflight_uploads.pop(resolved_path, None)

    task.add_done_callback(_cleanup_inflight)

    if enabled and auto_analyze and low_spec_mode:
        logger.info(
            "image_review_client: low-spec mode enabled, running review asynchronously for %s",
            resolved_path,
        )
        return True

    try:
        return await task
    finally:
        _cleanup_inflight(task)
