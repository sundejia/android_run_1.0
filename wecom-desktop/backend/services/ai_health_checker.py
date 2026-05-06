"""
AI Health Checker — two-layer probe (network + HTTP service).

Layer 1: TCP connectivity (is the host reachable?)
Layer 2: HTTP service alive (does /health or base URL respond?)

Results are stored via heartbeat_service.record_ai_health() and can
optionally force-open an AICircuitBreaker when the service is down.

NOTE: A previous Layer 3 (POST /chat with "ping") was removed because it
sent a real AI inference request every 5 minutes per device, wasting tokens
and inflating LangSmith traffic. The circuit breaker now relies solely on
actual business-call failures to detect AI outages.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


async def check_ai_health(ai_server_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Run the two-layer health probe and return a diagnostic dict."""
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

    # Both layers passed — service is reachable and HTTP-healthy.
    result["status"] = "healthy"
    result["response_time_ms"] = (time.monotonic() - overall_start) * 1000
    return result


# ----------------------------------------------------------------------------
# Severity model for probe results.
#
# BUG-2026-04-27-circuit-breaker-skip-reply showed that calling
# `circuit_breaker.force_open()` on EVERY non-healthy probe creates a
# "health-check lockup": each periodic probe re-forces the breaker open
# for `recovery_timeout`, repeatedly skipping customer replies even when
# real /chat traffic still completes successfully.
#
# We therefore classify probe statuses by severity:
#   - "fatal":   trip the breaker immediately.
#   - "severe":  trip the breaker only after N consecutive results.
#   - "warn":    log only; do NOT trip the breaker. The natural failure
#                threshold of AICircuitBreaker (record_failure x N) will
#                still catch real outages because actual /chat calls fail.
#   - "ok":      reset the consecutive-unhealthy counter.
# ----------------------------------------------------------------------------

_STATUS_SEVERITY: dict[str, str] = {
    "healthy": "ok",
    "unreachable": "fatal",
    "service_down": "severe",
    # Layer-3 style outcomes (not emitted by current check_ai_health, but still
    # handled for callers/tests and any future probe extensions — BUG-2026-04-27).
    "inference_timeout": "warn",
    "inference_error": "severe",
}


class PeriodicAIHealthChecker:
    """Runs `check_ai_health` at a fixed interval in the background."""

    def __init__(
        self,
        ai_server_url: str,
        interval_seconds: float = 300.0,
        circuit_breaker: Any | None = None,
        logger: Any | None = None,
        force_open_threshold: int = 2,
    ):
        self._url = ai_server_url
        self._interval = interval_seconds
        self._circuit_breaker = circuit_breaker
        self._logger = logger
        self._task: asyncio.Task | None = None
        self._last_result: dict[str, Any] | None = None
        # Consecutive-failure gate: how many consecutive "severe" probes are
        # required before we escalate to force_open(). "fatal" probes still
        # fire immediately. "warn" probes never fire.
        self._force_open_threshold = max(1, int(force_open_threshold))
        self._consecutive_unhealthy = 0
        # Once we've forced the breaker open for the current outage, do not
        # re-fire force_open() until we observe a recovery ("ok" probe).
        # This keeps logs clean and prevents the periodic health checker
        # from monopolising the breaker's lifecycle.
        self._already_forced_open = False

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # Severity-aware breaker control
    # ------------------------------------------------------------------

    def _handle_probe_result(self, result: dict[str, Any]) -> None:
        """Decide whether to escalate this probe to the circuit breaker.

        See module-level _STATUS_SEVERITY map for the policy. Designed to be
        unit-testable independently of the async loop / network layer.
        """
        status = result.get("status", "unknown")
        severity = _STATUS_SEVERITY.get(status, "severe")  # unknown -> severe

        if severity == "ok":
            if self._consecutive_unhealthy or self._already_forced_open:
                if self._logger:
                    self._logger.info("[AIHealthChecker] AI recovered; resetting unhealthy counter")
            self._consecutive_unhealthy = 0
            self._already_forced_open = False
            return

        if severity == "warn":
            # Degraded but not breaker-worthy (e.g. probe /chat timeout while
            # real traffic still completes). Do not increment the consecutive
            # gate or force_open — BUG-2026-04-27.
            if self._logger:
                self._logger.warning(
                    f"[AIHealthChecker] AI degraded ({status}) — warn only, not forcing circuit breaker open"
                )
            return

        # severity in {"severe", "fatal"} — count this probe.
        self._consecutive_unhealthy += 1

        if not self._circuit_breaker:
            return

        if self._already_forced_open:
            # Outage continues; breaker has already been forced open.
            # Don't keep re-firing force_open — the breaker's own timer
            # handles the half_open probing. The gate is reset only when
            # a healthy probe is observed.
            return

        should_force_open = severity == "fatal" or (self._consecutive_unhealthy >= self._force_open_threshold)
        if not should_force_open:
            if self._logger:
                self._logger.warning(
                    f"[AIHealthChecker] AI unhealthy ({status}), "
                    f"{self._consecutive_unhealthy}/{self._force_open_threshold} consecutive — "
                    "deferring force_open until threshold is met"
                )
            return

        try:
            self._circuit_breaker.force_open()
        except Exception as e:
            if self._logger:
                self._logger.error(f"[AIHealthChecker] force_open() raised: {e}")
            return

        self._already_forced_open = True
        if self._logger:
            self._logger.warning(
                f"[AIHealthChecker] AI unhealthy ({status}) for "
                f"{self._consecutive_unhealthy} consecutive probes, "
                "circuit breaker forced open"
            )

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

                # Severity-based force_open decision (BUG-2026-04-27 fix).
                self._handle_probe_result(result)

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
