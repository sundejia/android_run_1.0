"""
AI Health Checker — three-layer probe.

Layer 1: TCP connectivity (is the host reachable?)
Layer 2: HTTP service alive (does /health or base URL respond?)
Layer 3: End-to-end inference (does POST /chat return a valid answer?)

Results are stored via heartbeat_service.record_ai_health() and can
optionally force-open an AICircuitBreaker when the service is down.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


async def check_ai_health(ai_server_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Run the three-layer health probe and return a diagnostic dict."""
    from urllib.parse import urlparse

    import aiohttp

    parsed = urlparse(ai_server_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base_url = f"{parsed.scheme}://{host}:{port}"

    result: dict[str, Any] = {
        "ai_server_url": ai_server_url,
        "network": None,
        "http_service": None,
        "inference": None,
        "diagnosis": None,
        "response_time_ms": None,
        "status": "unknown",
    }

    overall_start = time.monotonic()

    # --- Layer 1: TCP connectivity ---
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
        writer.close()
        await writer.wait_closed()
        result["network"] = "reachable"
    except Exception:
        result["network"] = "unreachable"
        result["status"] = "unreachable"
        result["diagnosis"] = "AI server host unreachable (network / ECS issue)"
        result["response_time_ms"] = (time.monotonic() - overall_start) * 1000
        return result

    # --- Layer 2: HTTP service alive ---
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    result["http_service"] = "alive"
                else:
                    result["http_service"] = f"error_{resp.status}"
    except Exception:
        # /health may not exist — try the base URL
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(base_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    result["http_service"] = "alive" if resp.status < 500 else f"error_{resp.status}"
        except Exception:
            result["http_service"] = "dead"
            result["status"] = "service_down"
            result["diagnosis"] = "AI service process is not responding (ECS reachable but /chat service down)"
            result["response_time_ms"] = (time.monotonic() - overall_start) * 1000
            return result

    # --- Layer 3: End-to-end inference ---
    chat_url = ai_server_url if ai_server_url.endswith("/chat") else f"{base_url}/chat"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                chat_url,
                json={"chatInput": "ping", "sessionId": "health_check"},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    result["inference"] = "working"
                    result["status"] = "healthy"
                else:
                    result["inference"] = f"error_{resp.status}"
                    result["status"] = "inference_error"
                    result["diagnosis"] = (
                        "AI service online but inference failed (possible upstream model provider issue)"
                    )
    except TimeoutError:
        result["inference"] = "timeout"
        result["status"] = "inference_timeout"
        result["diagnosis"] = "AI inference timed out (possible upstream model provider overload)"
    except Exception as e:
        result["inference"] = f"error:{type(e).__name__}"
        result["status"] = "inference_error"
        result["diagnosis"] = f"AI inference request failed: {e}"

    result["response_time_ms"] = (time.monotonic() - overall_start) * 1000
    return result


class PeriodicAIHealthChecker:
    """Runs `check_ai_health` at a fixed interval in the background."""

    def __init__(
        self,
        ai_server_url: str,
        interval_seconds: float = 300.0,
        circuit_breaker: Any | None = None,
        logger: Any | None = None,
    ):
        self._url = ai_server_url
        self._interval = interval_seconds
        self._circuit_breaker = circuit_breaker
        self._logger = logger
        self._task: asyncio.Task | None = None
        self._last_result: dict[str, Any] | None = None

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                result = await check_ai_health(self._url)
                self._last_result = result

                # Persist to monitoring DB
                try:
                    from services.heartbeat_service import record_ai_health

                    record_ai_health(
                        ai_server_url=result["ai_server_url"],
                        status=result["status"],
                        response_time_ms=result.get("response_time_ms"),
                        error_message=result.get("diagnosis"),
                        network=result.get("network"),
                        http_service=result.get("http_service"),
                        inference=result.get("inference"),
                        diagnosis=result.get("diagnosis"),
                    )
                except Exception as db_err:
                    if self._logger:
                        self._logger.warning(f"[AIHealthChecker] DB write failed: {db_err}")

                # If AI is down and we have a circuit breaker, force it open
                if self._circuit_breaker and result["status"] not in ("healthy",):
                    self._circuit_breaker.force_open()
                    if self._logger:
                        self._logger.warning(
                            f"[AIHealthChecker] AI unhealthy ({result['status']}), circuit breaker forced open"
                        )

                if self._logger:
                    self._logger.info(
                        f"[AIHealthChecker] status={result['status']} "
                        f"network={result['network']} http={result['http_service']} "
                        f"inference={result['inference']} "
                        f"time={result.get('response_time_ms', 0):.0f}ms"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._logger:
                    self._logger.error(f"[AIHealthChecker] Unexpected error: {e}")

            await asyncio.sleep(self._interval)
