"""Async client that uploads a customer image to the image-rating-server.

This client owns only the OUTBOUND submission. The verdict comes back
asynchronously via the webhook receiver in ``wecom-desktop/backend``.

Design choices:
- Use a session_factory injection point so tests don't need a real network
  stack and we don't take a hard runtime dep on ``aiohttp`` here.
- Idempotency on the rating-server is keyed by ``correlation_id``, which we
  set to the android ``message_id`` (str). The server uses it as the webhook
  ``idempotency_key`` in turn.
- Errors raise ``ReviewSubmissionError``; callers usually log + skip.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewSubmissionResult:
    """Outcome of a successful submission: image_id assigned by rating-server."""

    image_id: str
    raw_analyze_response: dict[str, Any]


class ReviewSubmissionError(RuntimeError):
    """Raised when upload or analyze leg fails."""


def _default_session_factory():  # pragma: no cover - imported lazily
    import aiohttp

    return aiohttp.ClientSession()


class ReviewClient:
    """Submit images to the rating-server (upload then analyze)."""

    def __init__(
        self,
        *,
        rating_server_url: str,
        session_factory: Callable[[], Any] | None = None,
        request_timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        backoff_seconds: tuple[float, ...] = (1.0, 4.0, 16.0),
    ) -> None:
        self._url = rating_server_url.rstrip("/")
        self._session_factory = session_factory or _default_session_factory
        self._timeout = request_timeout_seconds
        self._max_attempts = max(1, int(max_attempts))
        self._backoff = backoff_seconds or (1.0,)

    async def submit(
        self,
        *,
        image_path: str,
        message_id: int,
    ) -> ReviewSubmissionResult:
        path = Path(image_path)
        if not path.is_file():
            raise ReviewSubmissionError(f"Image file not found: {image_path}")

        session = self._session_factory()

        last_error: Exception | None = None
        async with session as s:
            for attempt in range(self._max_attempts):
                try:
                    image_id = await self._upload(s, path)
                    analyze = await self._analyze(s, image_id, message_id)
                    return ReviewSubmissionResult(
                        image_id=image_id,
                        raw_analyze_response=analyze,
                    )
                except ReviewSubmissionError as exc:
                    last_error = exc
                    logger.warning(
                        "Review submission attempt %d/%d failed: %s",
                        attempt + 1,
                        self._max_attempts,
                        exc,
                    )
                    if attempt < self._max_attempts - 1:
                        await asyncio.sleep(
                            self._backoff[min(attempt, len(self._backoff) - 1)]
                        )

        raise ReviewSubmissionError(
            f"Review submission exhausted retries: {last_error}"
        )

    async def _upload(self, session: Any, path: Path) -> str:
        url = f"{self._url}/api/v1/upload"
        try:
            import aiohttp  # type: ignore

            data = aiohttp.FormData()
            data.add_field(
                "images",
                path.read_bytes(),
                filename=path.name,
                content_type="application/octet-stream",
            )
        except ImportError:
            data = {"images": (path.name, path.read_bytes())}

        async with session.post(url, data=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ReviewSubmissionError(
                    f"upload failed: HTTP {resp.status} {text[:200]}"
                )
            body = await resp.json()

        if not body or not body.get("success"):
            raise ReviewSubmissionError(f"upload returned non-success: {body!r}")
        results = body.get("results") or []
        if not results:
            raise ReviewSubmissionError("upload response has no results")
        first = results[0]
        if first.get("status") != "success":
            raise ReviewSubmissionError(
                f"upload result status={first.get('status')}: {first.get('error_message')}"
            )
        meta = first.get("metadata") or {}
        image_id = meta.get("image_id")
        if not image_id:
            raise ReviewSubmissionError("upload response missing image_id")
        return str(image_id)

    async def _analyze(self, session: Any, image_id: str, message_id: int) -> dict[str, Any]:
        url = f"{self._url}/api/v1/ai/analyze/{image_id}"
        payload = {"correlation_id": str(message_id)}
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ReviewSubmissionError(
                    f"analyze failed: HTTP {resp.status} {text[:200]}"
                )
            return await resp.json()
