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
import re
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
    return dict.fromkeys(_METRIC_KEYS, 0)


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


async def _default_shell_runner(adb_binary: str, serial: str, args: list[str]) -> tuple[int, bytes, bytes]:
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

            driver = AdbTools(serial=serial, use_tcp=use_tcp, remote_tcp_port=droidrun_port)

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
            self._log.warning("portal error on %s: %s; attempting self-heal", self._serial, exc)
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
        # DroidRun AdbTools has no tap_by_text; find the element by
        # scanning the current UI tree and tapping its centre via
        # ``tap_by_coordinates``.
        try:
            bounds = await self._find_bounds_native(text)
            if bounds is not None:
                cx = (bounds["left"] + bounds["right"]) // 2
                cy = (bounds["top"] + bounds["bottom"]) // 2
                self._log.debug("tap_by_text(%r) -> coordinates (%d, %d) on %s", text, cx, cy, self._serial)
                return bool(await self._adb.tap_by_coordinates(cx, cy))
            self._log.debug("tap_by_text(%r) element not found in tree on %s", text, self._serial)
            return False
        except Exception as exc:  # noqa: BLE001
            self._log.debug("native tap_by_text(%r) failed on %s: %s", text, self._serial, exc)
            return False

    async def tap(self, x: int, y: int) -> bool:
        if not self._fallback_active and hasattr(self._adb, "tap_by_coordinates"):
            try:
                return bool(await self._adb.tap_by_coordinates(x, y))
            except Exception:  # noqa: BLE001
                pass
        rc, _, _ = await self._shell(
            self._adb_binary,
            self._serial,
            ["shell", "input", "tap", str(x), str(y)],
        )
        return rc == 0

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        if self._fallback_active:
            await self._shell(
                self._adb_binary,
                self._serial,
                ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            )
            return
        await self._adb.swipe(x1, y1, x2, y2, duration_ms)

    async def type_text(self, text: str) -> bool:
        if self._fallback_active or not hasattr(self._adb, "input_text"):
            return await self._type_text_via_shell(text)
        try:
            result = await self._adb.input_text(text)
            return "error" not in str(result).lower()
        except Exception as exc:  # noqa: BLE001
            self._log.debug("native type_text failed on %s: %s", self._serial, exc)
            return await self._type_text_via_shell(text)

    async def press_back(self) -> None:
        """Press the Android BACK button (KEYCODE_BACK = 4)."""
        if not self._fallback_active and hasattr(self._adb, "press_key"):
            try:
                await self._adb.press_key(4)
                return
            except Exception:  # noqa: BLE001
                pass
        await self._shell(
            self._adb_binary,
            self._serial,
            ["shell", "input", "keyevent", "4"],
        )

    # --- Internals --------------------------------------------------

    async def _find_bounds_native(self, label: str) -> dict[str, int] | None:
        """Scan the native UI tree for a node whose text matches *label*
        and return its ``boundsInScreen`` dict."""
        tree, _ = await self._get_state_native()
        return _find_bounds_for_label(tree, label)

    async def _get_state_native(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        state = await self._adb.get_state()
        if not state:
            return {}, []
        tree = state[0] if state else {}
        elements = state[1] if len(state) > 1 else []
        if isinstance(tree, str):
            parsed_tree = _tree_from_clickable_state_text(tree)
            # Also try Part 2 (structured list) when available.
            structured = state[2] if len(state) > 2 and isinstance(state[2], list) else None
            if structured:
                tree_from_list = _tree_from_structured_elements(structured)
                if tree_from_list is not None:
                    return tree_from_list, []
            if parsed_tree is not None:
                return parsed_tree, []
            return {}, elements if isinstance(elements, list) else []
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
            self._log.warning("portal self-heal: force-stop + restart on %s", self._serial)
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


_CLICKABLE_LINE_RE = re.compile(
    r"^\s*\d+\.\s+(?P<class_name>[^:]+):\s+(?P<body>.*?)\s+-\s+"
    r"(?:bounds)?\((?P<left>-?\d+),(?P<top>-?\d+),(?P<right>-?\d+),(?P<bottom>-?\d+)\)\s*$"
)
_QUOTED_RE = re.compile(r'"([^"]*)"')


def _tree_from_clickable_state_text(state_text: str) -> dict[str, Any] | None:
    children: list[dict[str, Any]] = []
    for line in state_text.splitlines():
        match = _CLICKABLE_LINE_RE.match(line)
        if not match:
            continue
        quoted = _QUOTED_RE.findall(match.group("body"))
        resource_id = _resource_id_from_quoted(quoted)
        text = _text_from_quoted(quoted)
        children.append(
            {
                "resourceId": resource_id,
                "className": match.group("class_name").strip(),
                "text": text,
                "contentDescription": text,
                "boundsInScreen": {
                    "left": int(match.group("left")),
                    "top": int(match.group("top")),
                    "right": int(match.group("right")),
                    "bottom": int(match.group("bottom")),
                },
                "children": [],
            }
        )
    if not children:
        return None
    return {
        "resourceId": "",
        "className": "DroidRunClickableState",
        "text": "",
        "contentDescription": "",
        "boundsInScreen": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "children": children,
    }


def _resource_id_from_quoted(values: list[str]) -> str:
    for value in values:
        if ":id/" in value:
            return value
    return ""


def _text_from_quoted(values: list[str]) -> str:
    for value in reversed(values):
        if ":id/" not in value and not value.startswith("android."):
            return value
    return ""


def _tree_from_structured_elements(elements: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build a UI tree from DroidRun's Part-2 structured element list.

    Each element has ``index``, ``resourceId``, ``className``, ``text``,
    ``bounds`` (as ``"x1,y1,x2,y2"`` string), and optional ``children``.
    """
    children: list[dict[str, Any]] = []
    for el in elements:
        raw_text = el.get("text", "")
        rid = el.get("resourceId", "")
        cls = el.get("className", "")
        raw_bounds = el.get("bounds", "")
        el_children = el.get("children") or []

        # In DroidRun's Part 2, the ``text`` field sometimes contains
        # a resourceId (e.g. "com.hpbr.bosszhipin:id/parent") instead
        # of visible text.  Only use it as display text if it does NOT
        # look like a resource id.
        display_text = raw_text if not raw_text.startswith("com.") and ":id/" not in raw_text else ""

        bounds_dict: dict[str, int] = {}
        if isinstance(raw_bounds, str) and "," in raw_bounds:
            parts = raw_bounds.split(",")
            if len(parts) == 4:
                try:
                    bounds_dict = {
                        "left": int(parts[0]),
                        "top": int(parts[1]),
                        "right": int(parts[2]),
                        "bottom": int(parts[3]),
                    }
                except ValueError:
                    pass
        elif isinstance(raw_bounds, dict):
            bounds_dict = raw_bounds

        # Recursively convert children
        sub_children = _tree_from_structured_elements(el_children) if el_children else None

        node: dict[str, Any] = {
            "resourceId": rid,
            "className": cls,
            "text": display_text,
            "contentDescription": display_text,
            "boundsInScreen": bounds_dict,
            "children": sub_children["children"] if sub_children else [],
        }
        children.append(node)

    if not children:
        return None
    return {
        "resourceId": "",
        "className": "DroidRunStructured",
        "text": "",
        "contentDescription": "",
        "boundsInScreen": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "children": children,
    }


# --- Tree walking utilities -----------------------------------------


def _find_bounds_for_label(tree: dict[str, Any], label: str) -> dict[str, int] | None:
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
        if (node.get("text") or "").strip() == label or (node.get("contentDescription") or "").strip() == label:
            bounds = node.get("boundsInScreen")
            if isinstance(bounds, dict) and "left" in bounds and "right" in bounds and bounds["right"] > bounds["left"]:
                return bounds
    return None
