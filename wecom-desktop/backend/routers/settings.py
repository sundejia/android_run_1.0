"""
Settings Router - API endpoints for application settings management.

Provides endpoints for:
- Timezone configuration
- Settings persistence
- All application settings (database-backed)

Uses the new unified SettingsService for database-backed storage.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from wecom_automation.core.performance import runtime_metrics

from services.settings import (
    SettingCategory,
    get_settings_service,
)

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================


class TimezoneInfo(BaseModel):
    """Timezone information."""

    id: str = Field(..., description="IANA timezone identifier")
    display_name: str = Field(..., description="Human-readable display name")
    offset: str = Field(..., description="UTC offset (e.g., +08:00)")


class TimezonePreset(BaseModel):
    """Timezone preset for quick selection."""

    key: str = Field(..., description="Preset key")
    name: str = Field(..., description="Display name")
    timezone: str = Field(..., description="IANA timezone identifier")


class TimezoneSettings(BaseModel):
    """Current timezone settings."""

    timezone: str = Field(default="Asia/Shanghai", description="Current timezone")
    presets: List[TimezonePreset] = Field(default_factory=list, description="Available presets")


class UpdateTimezoneRequest(BaseModel):
    """Request to update timezone setting."""

    timezone: str = Field(..., description="IANA timezone identifier or preset key")


class VolcengineAsrSettings(BaseModel):
    """Volcengine ASR settings for voice transcription."""

    enabled: bool = Field(default=True, description="Enable voice transcription")
    api_key: str = Field(default="", description="Volcengine API key")
    resource_id: str = Field(default="volc.seedasr.auc", description="ASR resource ID")


class UpdateSettingsRequest(BaseModel):
    """
    Request to update application settings.
    Optional fields - only provided fields will be updated.
    """

    # AI Settings
    ai_server_url: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_style_key: Optional[str] = None  # 提示词风格预设
    ai_reply_timeout: Optional[int] = None
    ai_reply_max_length: Optional[int] = None
    use_ai_reply: Optional[bool] = None  # AI 回复开关

    # Sidecar Settings
    send_via_sidecar: Optional[bool] = None  # Sidecar 开关
    sidecar_poll_interval: Optional[int] = None
    countdown_seconds: Optional[int] = None
    sidecar_show_logs: Optional[bool] = None  # Sidecar 日志面板开关
    scan_interval: Optional[int] = None  # Realtime scan interval (seconds)

    # Generic settings (add more as needed)
    hostname: Optional[str] = None
    person_name: Optional[str] = None
    log_upload_enabled: Optional[bool] = None
    log_upload_time: Optional[str] = None
    log_upload_url: Optional[str] = None
    log_upload_token: Optional[str] = None
    timezone: Optional[str] = None
    email_enabled: Optional[bool] = None
    image_upload_enabled: Optional[bool] = None
    image_server_ip: Optional[str] = None
    image_review_timeout_seconds: Optional[int] = None
    low_spec_mode: Optional[bool] = None
    max_concurrent_sync_devices: Optional[int] = None
    sidecar_max_panels: Optional[int] = None

    # Dashboard Settings
    dashboard_enabled: Optional[bool] = None
    dashboard_url: Optional[str] = None


class SettingsResponse(BaseModel):
    """Full application settings response."""

    timezone: str = Field(default="Asia/Shanghai")
    volcengine_asr: VolcengineAsrSettings = Field(default_factory=VolcengineAsrSettings)


class UpdateVolcengineAsrRequest(BaseModel):
    """Request to update Volcengine ASR settings."""

    enabled: Optional[bool] = None
    api_key: Optional[str] = None
    resource_id: Optional[str] = None


class VolcengineAsrTestResponse(BaseModel):
    """Response from Volcengine ASR test."""

    success: bool
    message: str
    latency_ms: Optional[int] = None
    transcription: Optional[str] = None


class ImageReviewTestResponse(BaseModel):
    """Response from image review server test upload."""

    success: bool
    message: str
    latency_ms: Optional[int] = None


class SettingUpdateRequest(BaseModel):
    """Request to update a single setting."""

    value: Any
    changed_by: str = "api"


class PerformanceProfileResponse(BaseModel):
    lowSpecMode: bool
    effective: Dict[str, Any]
    metrics: Dict[str, Any]


# ============================================================================
# Timezone Presets
# ============================================================================

TIMEZONE_PRESETS = [
    TimezonePreset(key="china", name="中国 (北京/上海)", timezone="Asia/Shanghai"),
    TimezonePreset(key="hongkong", name="香港", timezone="Asia/Hong_Kong"),
    TimezonePreset(key="taiwan", name="台湾", timezone="Asia/Taipei"),
    TimezonePreset(key="singapore", name="新加坡", timezone="Asia/Singapore"),
    TimezonePreset(key="tokyo", name="日本 (东京)", timezone="Asia/Tokyo"),
    TimezonePreset(key="seoul", name="韩国 (首尔)", timezone="Asia/Seoul"),
    TimezonePreset(key="us_pacific", name="美国太平洋时间", timezone="America/Los_Angeles"),
    TimezonePreset(key="us_eastern", name="美国东部时间", timezone="America/New_York"),
    TimezonePreset(key="uk", name="英国 (伦敦)", timezone="Europe/London"),
    TimezonePreset(key="utc", name="UTC", timezone="UTC"),
]

PRESET_MAP = {p.key: p.timezone for p in TIMEZONE_PRESETS}


# ============================================================================
# Settings Persistence (database-backed)
# ============================================================================


def load_settings() -> Dict:
    """Load settings from database."""
    service = get_settings_service()
    flat = service.get_flat_settings()

    # Add volcengine_asr nested structure for backward compatibility
    volcengine = service.get_volcengine_settings()
    flat["volcengine_asr"] = {
        "enabled": volcengine.enabled,
        "api_key": volcengine.api_key,
        "resource_id": volcengine.resource_id,
    }

    return flat


def save_settings(settings: Dict) -> None:
    """Save settings to database."""
    service = get_settings_service()
    service.update_from_flat(settings, "api")


def get_timezone_offset(tz_name: str) -> str:
    """Get UTC offset string for a timezone."""
    try:
        from datetime import datetime

        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        offset = now.utcoffset()
        if offset is None:
            return "+00:00"
        total_seconds = int(offset.total_seconds())
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes = remainder // 60
        sign = "+" if total_seconds >= 0 else "-"
        return f"{sign}{hours:02d}:{minutes:02d}"
    except Exception:
        return "+00:00"


# ============================================================================
# API Endpoints - Timezone
# ============================================================================


@router.get("/timezone", response_model=TimezoneSettings)
async def get_timezone_settings():
    """Get current timezone settings and available presets."""
    service = get_settings_service()
    current_tz = service.get_timezone()

    return TimezoneSettings(
        timezone=current_tz,
        presets=TIMEZONE_PRESETS,
    )


@router.put("/timezone", response_model=TimezoneSettings)
async def update_timezone(request: UpdateTimezoneRequest):
    """
    Update the timezone setting.

    Accepts either an IANA timezone identifier (e.g., "Asia/Shanghai")
    or a preset key (e.g., "china").
    """
    timezone = request.timezone.strip()

    # Check if it's a preset key
    if timezone.lower() in PRESET_MAP:
        timezone = PRESET_MAP[timezone.lower()]

    # Validate timezone
    try:
        ZoneInfo(timezone)
    except Exception:
        raise HTTPException(
            status_code=400, detail=f"Invalid timezone: {timezone}. Please use a valid IANA timezone identifier."
        )

    # Save to database
    service = get_settings_service()
    service.set_timezone(timezone, "api")

    # Update environment variable for current process
    os.environ["WECOM_TIMEZONE"] = timezone

    return TimezoneSettings(
        timezone=timezone,
        presets=TIMEZONE_PRESETS,
    )


@router.get("/timezone/search")
async def search_timezones(q: str = "") -> List[TimezoneInfo]:
    """
    Search available timezones.

    Args:
        q: Search query (searches in timezone ID)
    """
    results = []
    query = q.lower()

    # Get all available timezones
    all_tzs = sorted(available_timezones())

    for tz_name in all_tzs:
        if query and query not in tz_name.lower():
            continue

        # Create display name from timezone ID
        display_name = tz_name.replace("_", " ")
        offset = get_timezone_offset(tz_name)

        results.append(
            TimezoneInfo(
                id=tz_name,
                display_name=display_name,
                offset=offset,
            )
        )

        # Limit results
        if len(results) >= 50:
            break

    return results


# ============================================================================
# API Endpoints - All Settings
# ============================================================================


@router.get("")
async def get_all_settings():
    """Get all application settings (flat format for frontend)."""
    return load_settings()


@router.get("/presets")
async def get_timezone_presets() -> List[TimezonePreset]:
    """Get timezone presets for quick selection."""
    return TIMEZONE_PRESETS


@router.post("/update")
async def update_settings(request: UpdateSettingsRequest):
    """
    Update application settings.

    This is a generic endpoint to sync frontend settings (localStorage)
    with the backend persistence (database).
    """
    service = get_settings_service()

    # Build update dict from request
    updates = {}
    if request.ai_server_url:
        updates["aiServerUrl"] = request.ai_server_url
    if request.system_prompt is not None:  # Allow empty string
        updates["systemPrompt"] = request.system_prompt
    if request.prompt_style_key is not None:  # 提示词风格预设
        updates["promptStyleKey"] = request.prompt_style_key
    if request.ai_reply_timeout is not None:
        updates["aiReplyTimeout"] = request.ai_reply_timeout
    # Note: ai_reply_max_length is deprecated and no longer used in prompt generation
    if request.use_ai_reply is not None:  # AI 回复开关
        updates["useAIReply"] = request.use_ai_reply

    # Sidecar settings
    if request.send_via_sidecar is not None:  # Sidecar 开关
        updates["sendViaSidecar"] = request.send_via_sidecar
    if request.sidecar_poll_interval is not None:
        updates["sidecarPollInterval"] = request.sidecar_poll_interval
    if request.countdown_seconds is not None:
        updates["countdownSeconds"] = request.countdown_seconds
    if request.sidecar_show_logs is not None:  # Sidecar 日志面板开关
        updates["sidecarShowLogs"] = request.sidecar_show_logs
    if request.scan_interval is not None:
        updates["scanInterval"] = request.scan_interval

    if request.hostname is not None:
        updates["hostname"] = service.normalize_hostname_input(request.hostname)
    if request.person_name is not None:
        updates["personName"] = service.normalize_person_name_input(request.person_name)
    if request.log_upload_enabled is not None:
        updates["logUploadEnabled"] = request.log_upload_enabled
    if request.log_upload_time is not None:
        updates["logUploadTime"] = request.log_upload_time.strip() or "02:00"
    if request.log_upload_url is not None:
        updates["logUploadUrl"] = request.log_upload_url.strip()
    if request.log_upload_token is not None:
        updates["logUploadToken"] = request.log_upload_token.strip()
    if request.timezone:
        updates["timezone"] = request.timezone
        try:
            os.environ["WECOM_TIMEZONE"] = request.timezone
        except:
            pass
    if request.email_enabled is not None:
        updates["emailEnabled"] = request.email_enabled
    if request.image_upload_enabled is not None:
        updates["imageUploadEnabled"] = request.image_upload_enabled
    if request.image_server_ip is not None:
        updates["imageServerIp"] = request.image_server_ip.strip()
    if request.image_review_timeout_seconds is not None:
        updates["imageReviewTimeoutSeconds"] = request.image_review_timeout_seconds
    if request.low_spec_mode is not None:
        updates["lowSpecMode"] = request.low_spec_mode
    if request.max_concurrent_sync_devices is not None:
        updates["maxConcurrentSyncDevices"] = request.max_concurrent_sync_devices
    if request.sidecar_max_panels is not None:
        updates["sidecarMaxPanels"] = request.sidecar_max_panels

    # Dashboard settings
    if request.dashboard_enabled is not None:
        updates["dashboardEnabled"] = request.dashboard_enabled
    if request.dashboard_url is not None:
        updates["dashboardUrl"] = request.dashboard_url.strip()

    # Update in database
    service.update_from_frontend_partial(updates, "frontend")

    # If dashboard settings changed, reload the heartbeat client
    if request.dashboard_enabled is not None or request.dashboard_url is not None:
        try:
            from services.dashboard_service import get_dashboard_service

            new_dashboard = service.get_dashboard_settings()
            await get_dashboard_service().reload(
                enabled=new_dashboard.enabled,
                url=new_dashboard.url or "",
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("dashboard_reload_after_save: %s", exc)

    return {"success": True, "message": "Settings updated"}


# ============================================================================
# API Endpoints - New Unified Settings API
# ============================================================================


@router.get("/all")
async def get_all_settings_structured():
    """Get all settings in structured format (by category)."""
    service = get_settings_service()
    all_settings = service.get_all_settings()
    return all_settings.to_dict()


@router.get("/performance/profile", response_model=PerformanceProfileResponse)
async def get_performance_profile():
    """Get resolved low-spec profile plus runtime baseline metrics."""
    service = get_settings_service()
    profile = service.get_performance_profile()
    profile["metrics"] = runtime_metrics.snapshot()
    return PerformanceProfileResponse(**profile)


@router.get("/category/{category}")
async def get_category_settings(category: str):
    """Get all settings for a specific category."""
    try:
        # Validate category
        SettingCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    service = get_settings_service()
    return service.get_category(category)


@router.put("/category/{category}")
async def update_category_settings(category: str, settings: Dict[str, Any]):
    """Update multiple settings in a category."""
    try:
        SettingCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    service = get_settings_service()
    return service.set_category(category, settings, "api")


@router.put("/{category}/{key}")
async def update_single_setting(category: str, key: str, request: SettingUpdateRequest):
    """Update a single setting."""
    try:
        SettingCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    service = get_settings_service()
    record = service.set(category, key, request.value, request.changed_by)
    if record:
        return record.to_dict()
    raise HTTPException(status_code=404, detail="Setting not found")


@router.post("/category/{category}/reset")
async def reset_category_to_defaults(category: str):
    """Reset all settings in a category to defaults."""
    try:
        SettingCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    service = get_settings_service()
    return service.reset_category(category, "reset")


# ============================================================================
# Volcengine ASR Settings (backward compatible endpoints)
# ============================================================================


@router.get("/volcengine-asr", response_model=VolcengineAsrSettings)
async def get_volcengine_asr_settings():
    """Get Volcengine ASR settings."""
    service = get_settings_service()
    volcengine = service.get_volcengine_settings()
    return VolcengineAsrSettings(
        enabled=volcengine.enabled,
        api_key=volcengine.api_key,
        resource_id=volcengine.resource_id,
    )


@router.put("/volcengine-asr", response_model=VolcengineAsrSettings)
async def update_volcengine_asr_settings(request: UpdateVolcengineAsrRequest):
    """Update Volcengine ASR settings."""
    service = get_settings_service()

    if request.enabled is not None:
        service.set(SettingCategory.VOLCENGINE.value, "enabled", request.enabled, "api")
    if request.api_key is not None:
        service.set(SettingCategory.VOLCENGINE.value, "api_key", request.api_key, "api")
    if request.resource_id is not None:
        service.set(SettingCategory.VOLCENGINE.value, "resource_id", request.resource_id, "api")

    volcengine = service.get_volcengine_settings()
    return VolcengineAsrSettings(
        enabled=volcengine.enabled,
        api_key=volcengine.api_key,
        resource_id=volcengine.resource_id,
    )


@router.post("/volcengine-asr/test", response_model=VolcengineAsrTestResponse)
async def test_volcengine_asr():
    """
    Test Volcengine ASR connection by submitting a small test audio.

    Uses a public test audio URL from Volcengine's documentation.
    """
    import time
    import uuid

    import httpx

    service = get_settings_service()
    volcengine = service.get_volcengine_settings()

    api_key = volcengine.api_key
    resource_id = volcengine.resource_id

    if not api_key:
        return VolcengineAsrTestResponse(
            success=False,
            message="API key is not configured",
        )

    # Use a short test audio from Volcengine's documentation
    test_audio_url = "https://lf3-static.bytednsdoc.com/obj/eden-cn/lm_hz_ihsph/ljhwZthlaukjlkulzlp/console/bigtts/zh_female_cancan_mars_bigtts.mp3"

    request_id = str(uuid.uuid4())
    submit_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    query_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }

    submit_payload = {
        "user": {"uid": "wecom_test"},
        "audio": {"url": test_audio_url, "format": "mp3", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": False,
            "enable_speaker_info": False,
            "enable_channel_split": False,
            "show_utterances": False,
            "vad_segment": False,
            "sensitive_words_filter": "",
        },
    }

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Submit the test audio
            submit_response = await client.post(
                submit_url,
                headers=headers,
                json=submit_payload,
            )

            if submit_response.status_code != 200:
                return VolcengineAsrTestResponse(
                    success=False,
                    message=f"Submit failed: HTTP {submit_response.status_code}",
                    latency_ms=int((time.time() - start_time) * 1000),
                )

            submit_result = submit_response.json()

            # Check for immediate errors in response
            if submit_result.get("code") and submit_result.get("code") not in [0, 20000000, 20000001, 20000002]:
                return VolcengineAsrTestResponse(
                    success=False,
                    message=f"API error: {submit_result.get('message', 'Unknown error')} (code: {submit_result.get('code')})",
                    latency_ms=int((time.time() - start_time) * 1000),
                )

            # Query for result (poll a few times)
            query_headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "X-Api-Resource-Id": resource_id,
                "X-Api-Request-Id": request_id,
            }

            # Poll for up to 15 seconds (for test)
            max_attempts = 8
            poll_interval = 2

            for _ in range(max_attempts):
                await asyncio.sleep(poll_interval)

                query_response = await client.post(
                    query_url,
                    headers=query_headers,
                    json={},
                )

                if query_response.status_code != 200:
                    continue

                query_result = query_response.json()

                # Check if result is ready
                result = query_result.get("result", {})
                if result.get("text"):
                    latency_ms = int((time.time() - start_time) * 1000)
                    return VolcengineAsrTestResponse(
                        success=True,
                        message="Connection successful!",
                        latency_ms=latency_ms,
                        transcription=result["text"][:100] + ("..." if len(result["text"]) > 100 else ""),
                    )

                # Check error codes
                code = query_result.get("code")
                if code and code not in [20000001, 20000002]:  # Still processing
                    if code == 20000000:  # Success but no text?
                        continue
                    return VolcengineAsrTestResponse(
                        success=False,
                        message=f"Query error: {query_result.get('message', 'Unknown')} (code: {code})",
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

            # Timeout waiting for result - but connection worked
            return VolcengineAsrTestResponse(
                success=True,
                message="Connection OK (transcription still processing)",
                latency_ms=int((time.time() - start_time) * 1000),
            )

    except httpx.TimeoutException:
        return VolcengineAsrTestResponse(
            success=False,
            message="Request timed out",
            latency_ms=int((time.time() - start_time) * 1000),
        )
    except Exception as e:
        return VolcengineAsrTestResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
            latency_ms=int((time.time() - start_time) * 1000),
        )


# ============================================================================
# Image Review Server Test
# ============================================================================


@router.post("/image-review/test", response_model=ImageReviewTestResponse)
async def test_image_review_upload():
    """
    Test connectivity to the configured image review server by uploading a
    small synthetic JPEG image with auto_analyze=true.

    Returns success/failure and round-trip latency.
    """
    import io
    import struct
    import time

    import httpx

    service = get_settings_service()
    server_url = service.get_image_server_ip()

    if not server_url:
        return ImageReviewTestResponse(
            success=False,
            message="图片审核服务器地址未配置，请先填写服务器地址",
        )

    start_time = time.time()

    # Build a minimal valid 1×1 white JPEG in memory (no Pillow dependency)
    # This is a well-known minimal JPEG byte sequence for a 1×1 white pixel.
    minimal_jpeg = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00,
        0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB,
        0x00, 0x43, 0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07,
        0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B,
        0x0B, 0x0C, 0x19, 0x12, 0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E,
        0x1D, 0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C,
        0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29, 0x2C, 0x30, 0x31, 0x34, 0x34,
        0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
        0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01,
        0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00, 0x01, 0x05,
        0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01,
        0x03, 0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00,
        0x01, 0x7D, 0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21,
        0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32,
        0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1,
        0xF0, 0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0A, 0x16, 0x17, 0x18,
        0x19, 0x1A, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x34, 0x35, 0x36,
        0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
        0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64,
        0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75, 0x76, 0x77,
        0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A,
        0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5,
        0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
        0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9,
        0xDA, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA,
        0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF,
        0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD2,
        0x8A, 0x28, 0x03, 0xFF, 0xD9,
    ])

    server_url = server_url.rstrip("/")
    upload_url = f"{server_url}/api/v1/upload"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                upload_url,
                files={"images": ("wecom_test.jpg", io.BytesIO(minimal_jpeg), "image/jpeg")},
                data={"auto_analyze": "true"},
            )

        latency_ms = int((time.time() - start_time) * 1000)

        if response.status_code in (200, 201):
            body = response.json()
            succeeded = body.get("succeeded", 0)
            duplicated = body.get("duplicated", 0)
            detail = f"上传成功（新增 {succeeded}，重复 {duplicated}）" if succeeded or duplicated else "已接收"
            return ImageReviewTestResponse(
                success=True,
                message=detail,
                latency_ms=latency_ms,
            )
        elif response.status_code == 401:
            return ImageReviewTestResponse(
                success=False,
                message="认证失败（401）",
                latency_ms=latency_ms,
            )
        else:
            return ImageReviewTestResponse(
                success=False,
                message=f"服务器返回 HTTP {response.status_code}",
                latency_ms=latency_ms,
            )

    except httpx.ConnectError:
        return ImageReviewTestResponse(
            success=False,
            message=f"无法连接到 {server_url}，请确认地址和端口是否正确",
            latency_ms=int((time.time() - start_time) * 1000),
        )
    except httpx.TimeoutException:
        return ImageReviewTestResponse(
            success=False,
            message="请求超时（15s）",
            latency_ms=int((time.time() - start_time) * 1000),
        )
    except Exception as exc:
        return ImageReviewTestResponse(
            success=False,
            message=f"连接失败: {exc}",
            latency_ms=int((time.time() - start_time) * 1000),
        )


# ============================================================================
# Dashboard Heartbeat Settings
# ============================================================================


@router.get("/dashboard/status")
async def get_dashboard_status():
    """Get dashboard heartbeat client connection status."""
    try:
        from services.dashboard_service import get_dashboard_service
        return get_dashboard_service().status()
    except Exception:
        service = get_settings_service()
        dashboard = service.get_dashboard_settings()
        return {
            "enabled": dashboard.enabled,
            "url": dashboard.url,
            "status": "unknown",
        }


@router.post("/dashboard/test")
async def test_dashboard_connection(request: Optional[Dict[str, str]] = None):
    """Test connection to the device-dashboard."""
    try:
        from services.dashboard_service import get_dashboard_service
        url = (request or {}).get("url", "").strip() if request else ""
        return await get_dashboard_service().test_connection(url or None)
    except RuntimeError:
        from services.heartbeat_client import HeartbeatClient

        service = get_settings_service()
        dashboard = service.get_dashboard_settings()
        url = (request or {}).get("url", "").strip() or dashboard.url
        if not url:
            return {"success": False, "message": "Dashboard URL is not configured"}
        client = HeartbeatClient(
            dashboard_url=url,
            settings_service=service,
        )
        return await client.test_connection()
