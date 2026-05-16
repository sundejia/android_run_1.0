"""
HTTP client for uploading android_run_test log files.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


class LogUploadClient:
    """Uploads files to the recruitment data platform."""

    def __init__(self, timeout_seconds: float = 120.0):
        self._timeout = timeout_seconds

    async def upload_file(
        self,
        *,
        base_url: str,
        device_id: str,
        hostname: str,
        person_name: str,
        upload_kind: str,
        checksum: str,
        uploaded_at: datetime,
        file_path: Path,
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}/api/android-logs/upload"
        data = {
            "device_id": device_id,
            "hostname": hostname,
            "person_name": person_name,
            "upload_kind": upload_kind,
            "checksum": checksum,
            "uploaded_at": uploaded_at.isoformat(),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                with file_path.open("rb") as fh:
                    response = await client.post(
                        url,
                        data=data,
                        files={"file": (file_path.name, fh, "application/octet-stream")},
                    )
            response.raise_for_status()
            payload = response.json()
            inner_data = payload.get("data", payload)
            payload_success = bool(payload.get("success", True))
            return {
                "success": payload_success,
                "status_code": response.status_code,
                "data": inner_data,
                "error": payload.get("error") if not payload_success else None,
            }
        except httpx.HTTPStatusError as exc:
            detail = None
            try:
                detail = exc.response.json()
            except Exception:
                detail = exc.response.text
            return {
                "success": False,
                "status_code": exc.response.status_code,
                "error": detail,
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "status_code": None,
                "error": "Upload request timed out",
            }
        except Exception as exc:
            return {
                "success": False,
                "status_code": None,
                "error": str(exc),
            }
