"""Production adapter from DroidRun's ``AdbTools`` to the BOSS ``AdbPort``.

Previously lived inside ``wecom-desktop/backend/scripts/boss_sync_jobs.py``
as a private class. Lifted here in PR1 of the 2026-05-08 E2E fix so
both the FastAPI backend (``main.py``) and the CLI script share a
single resilient implementation.

Resilience strategy
-------------------
Real-device testing on 2026-05-08 showed the DroidRun accessibility
portal becomes non-responsive after entering BOSS Zhipin's
``PositionListManagementActivity``: ``get_state`` reports
"Portal returned error: Unknown error" and three internal retries
all fail. Even manual ``am force-stop com.droidrun.portal`` plus
portal restart did not recover the session.

This adapter wraps ``get_state`` in two defensive layers:

1. **Self-heal** — on portal error, sleep briefly and retry. If that
   fails too, ``am force-stop`` the portal, give accessibility services
   time to re-register, then retry once more.
2. **uiautomator fallback** — if self-heal still fails, flip the
   adapter into a fallback mode where ``get_state`` uses
   ``adb exec-out uiautomator dump``. Subsequent ``tap_by_text`` /
   ``swipe`` / ``type_text`` calls route through raw ``adb shell input``
   commands. The fallback is **sticky** for the adapter's lifetime:
   once the portal has broken on a device we assume it will keep
   breaking until the process restarts.

All resilience events increment module-level counters exposed via
``get_resilience_metrics``; the monitoring router publishes them so
operators can see how often the fallback is in use.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from boss_automation.services.uiautomator_fallback import (
    UiAutomatorFallbackError,
    dump_ui_tree,
)

__all__ = [
    "DroidRunAdapter",
    "get_resilience_metrics",
    "reset_resilience_metrics",
]


_LOGGER = logging.getLogger("boss_automation.droidrun_adapter")

_METRIC_KEYS: tuple[str, ...] = (
    "portal_retry",
    "portal_self_heal",
    "uiautomator_fallback_engaged",
    "fallback_mode_calls",
)

_METRICS: dict[str, dict[str, int]] = {}


def get_resilience_metrics(serial: str | None = None) -> dict[str, dict[str, int]]:
    """Return a snapshot of per-device resilience counters.

    Exposed for the monitoring endpoint so the dashboard can show
    whether the portal fallback is engaged on any device.
    """
    if serial is not None:
        return {serial: dict(_METRICS.get(serial, _empty_metrics()))}
    return {s: dict(m) for s, m in _METRICS.items()}


def reset_resilience_metrics() -> None:
    """Test hook: wipe all metrics."""
    _METRICS.clear()


def _empty_metrics() -> dict[str, int]:
    return {k: 0 for k in _METRIC_KEYS}


def _incr(serial: str, key: str) -> None:
    bucket = _METRICS.setdefault(serial, _empty_metrics())
    bucket[key] = bucket.get(key, 0) + 1


# --- Portal error recognition ---------------------------------------

_PORTAL_ERROR_TOKENS: tuple[str, ...] = (
    "portal returned error",
    "portal not responding",
    "failed to get state",
    "unknown error",
)


def _is_portal_error(exc: BaseException) -> bool:
    """Heuristic: does this exception look like a DroidRun portal hiccup?

    DroidRun raises a bare ``Exception`` with a stringly-typed message
    (``Failed to get state after 3 attempts: Portal returned error:
    Unknown error``) rather than a typed exception class, so we have
    to match on substrings. Kept narrow to avoid hiding real bugs —
    e.g. ``ConnectionRefusedError`` from adb is not a portal error.
    """
    msg = str(exc).lower()
    return any(tok in msg for tok in _PORTAL_ERROR_TOKENS)


# --- Shell runner boundary ------------------------------------------

# Injectable so tests can avoid spawning real adb subprocesses.
ShellRunner = Callable[[str, str, list[str]], Awaitable[tuple[int, bytes, bytes]]]


async def _default_shell_runner(
    adb_binary: str, serial: str, args: list[str]
) -> tuple[int, bytes, bytes]:
    """Execute ``adb -s <serial> <args...>`` and return (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        adb_binary,
        "-s",
        serial,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout, stderr


# --- DumpRunner boundary --------------------------------------------

DumpRunner = Callable[[str], Awaitable[dict[str, Any]]]


async def _default_dump_runner(serial: str) -> dict[str, Any]:
    return await dump_ui_tree(serial)


# --- Adapter --------------------------------------------------------


class DroidRunAdapter:
    """Adapt ``droidrun.AdbTools`` to the BOSS ``AdbPort`` Protocol with
    portal-resilience layered on top.

    Construct once per device-sync pass. The adapter is not designed
    for cross-process reuse.
    """

    def __init__(
        self,
        serial: str,
        *,
        use_tcp: bool = False,
        droidrun_port: int = 8080,
        adb_binary: str = "adb",
        driver: Any | None = None,
        shell_runner: ShellRunner | None = None,
        dump_runner: DumpRunner | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if driver is None:
            from droidrun import AdbTools  # type: ignore[import-untyped]

            driver = AdbTools(
                serial=serial, use_tcp=use_tcp, remote_tcp_port=droidrun_port
            )

        self._serial = serial
        self._adb_binary = adb_binary
        self._adb = driver
        self._shell: ShellRunner = shell_runner or _default_shell_runner
        self._dump: DumpRunner = dump_runner or _default_dump_runner
        self._sleep = sleeper or asyncio.sleep
        self._log = logger or _LOGGER
        self._fallback_active = False
        self._heal_lock = asyncio.Lock()

        _METRICS.setdefault(serial, _empty_metrics())

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    # --- AdbPort Protocol methods -----------------------------------

    async def start_app(self, package_name: str) -> None:
        await self._adb.start_app(package_name)

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._fallback_active:
            return await self._get_state_fallback()

        try:
            return await self._get_state_native()
        except Exception as exc:
            if not _is_portal_error(exc):
                raise
            self._log.warning(
                "portal error on %s: %s; attempting self-heal", self._serial, exc
            )
            _incr(self._serial, "portal_retry")
            try:
                return await self._self_heal_and_retry()
            except Exception as final_exc:
                self._log.warning(
                    "portal unrecoverable on %s (%s); engaging uiautomator fallback",
                    self._serial,
                    final_exc,
                )
                _incr(self._serial, "uiautomator_fallback_engaged")
                self._fallback_active = True
                return await self._get_state_fallback()

    async def tap_by_text(self, text: str) -> bool:
        if self._fallback_active:
            return await self._tap_by_text_fallback(text)
        try:
            return bool(await self._adb.tap_by_text(text))
        except Exception as exc:  # noqa: BLE001
            self._log.debug("native tap_by_text(%r) failed on %s: %s", text, self._serial, exc)
            return False

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> None:
        if self._fallback_active:
            await self._shell(
                self._adb_binary,
                self._serial,
                ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            )
            return
        await self._adb.swipe(x1, y1, x2, y2, duration_ms)

    async def type_text(self, text: str) -> bool:
        if self._fallback_active or not hasattr(self._adb, "type_text"):
            return await self._type_text_via_shell(text)
        try:
            return bool(await self._adb.type_text(text))
        except Exception as exc:  # noqa: BLE001
            self._log.debug("native type_text failed on %s: %s", self._serial, exc)
            return False

    # --- Internals --------------------------------------------------

    async def _get_state_native(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        state = await self._adb.get_state()
        if not state:
            return {}, []
        tree = state[0] if state else {}
        elements = state[1] if len(state) > 1 else []
        return tree, elements

    async def _get_state_fallback(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        _incr(self._serial, "fallback_mode_calls")
        try:
            tree = await self._dump(self._serial)
        except UiAutomatorFallbackError:
            # Dump itself failed — let the caller see the underlying
            # error so it can decide whether to give up vs. retry the
            # whole operation. We never swallow a dump failure silently
            # because a dead fallback is worse than a loud error.
            raise
        return tree, []

    async def _self_heal_and_retry(
        self,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        async with self._heal_lock:
            # Step 1: brief sleep + simple retry. Recovers from single
            # lost packets / race conditions inside the portal.
            await self._sleep(0.5)
            try:
                return await self._get_state_native()
            except Exception as exc:
                if not _is_portal_error(exc):
                    raise

            # Step 2: force-stop portal, let accessibility services
            # re-register, retry.
            _incr(self._serial, "portal_self_heal")
            self._log.warning(
                "portal self-heal: force-stop + restart on %s", self._serial
            )
            await self._shell(
                self._adb_binary,
                self._serial,
                ["shell", "am", "force-stop", "com.droidrun.portal"],
            )
            await self._sleep(2.0)
            # Best-effort re-activation. Ignore failures; portal's
            # auto-start on accessibility service registration is the
            # usual path, this is belt-and-suspenders.
            await self._shell(
                self._adb_binary,
                self._serial,
                [
                    "shell",
                    "am",
                    "start-service",
                    "com.droidrun.portal/.accessibility.DroidRunAccessibilityService",
                ],
            )
            await self._sleep(3.0)
            return await self._get_state_native()

    async def _tap_by_text_fallback(self, text: str) -> bool:
        tree, _ = await self._get_state_fallback()
        bounds = _find_bounds_for_label(tree, text)
        if bounds is None:
            return False
        cx = (bounds["left"] + bounds["right"]) // 2
        cy = (bounds["top"] + bounds["bottom"]) // 2
        rc, _, _ = await self._shell(
            self._adb_binary,
            self._serial,
            ["shell", "input", "tap", str(cx), str(cy)],
        )
        return rc == 0

    async def _type_text_via_shell(self, text: str) -> bool:
        # ``adb shell input text`` requires space → ``%s`` and strips
        # most punctuation. For the BOSS flows we only type ASCII
        # template bodies and candidate replies, so this is sufficient;
        # richer input would need an IME-based approach.
        escaped = text.replace(" ", "%s")
        rc, _, _ = await self._shell(
            self._adb_binary,
            self._serial,
            ["shell", "input", "text", escaped],
        )
        return rc == 0


# --- Tree walking utilities -----------------------------------------


def _find_bounds_for_label(
    tree: dict[str, Any], label: str
) -> dict[str, int] | None:
    """Depth-first search for the first node whose ``text`` or
    ``contentDescription`` matches ``label`` exactly.

    Returns the node's ``boundsInScreen`` dict, or ``None`` if no such
    node exists or its bounds are malformed.
    """

    def walk(node: dict[str, Any]) -> Any:
        if not isinstance(node, dict):
            return
        yield node
        for child in node.get("children", []) or []:
            yield from walk(child)

    for node in walk(tree):
        if (node.get("text") or "").strip() == label or (
            node.get("contentDescription") or ""
        ).strip() == label:
            bounds = node.get("boundsInScreen")
            if (
                isinstance(bounds, dict)
                and "left" in bounds
                and "right" in bounds
                and bounds["right"] > bounds["left"]
            ):
                return bounds
    return None
