"""Fallback UI tree capture via Android's native ``uiautomator dump``.

Used when the DroidRun accessibility portal crashes or returns errors
on a BOSS Zhipin screen (notably ``PositionListManagementActivity`` on
the 2026-05 app version). System-native ``uiautomator`` is not coupled
to DroidRun's portal app and keeps working even when the portal is
stuck.

Converts the XML dump into the same nested-dict schema that
``droidrun.AdbTools.get_state()`` returns, so every BOSS parser
(``recruiter_profile_parser``, ``job_list_parser``, etc.) continues to
work unmodified.

Schema mapping (uiautomator XML attribute → DroidRun tree key):
    resource-id    → resourceId
    class          → className
    package        → packageName
    text           → text
    content-desc   → contentDescription
    bounds         → boundsInScreen (and boundsInParent as a copy)
    clickable      → isClickable
    long-clickable → isLongClickable
    checkable/checked/enabled/focusable/focused/selected/scrollable
                   → isCheckable / isChecked / ...

Fields absent in the XML (``hint``, ``stateDescription``, ``tooltipText``,
``paneTitle``, ``error``, ``isContextClickable``, ``isAccessibilityFocused``,
``isVisibleToUser``) default to ``""`` or ``False`` to match the shape
parsers observe on real fixtures.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from xml.etree import ElementTree as ET

__all__ = [
    "UiAutomatorFallbackError",
    "dump_ui_tree",
    "parse_uiautomator_xml",
]

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


class UiAutomatorFallbackError(RuntimeError):
    """Raised when ``adb exec-out uiautomator dump`` fails or returns
    output we cannot parse.

    Callers are expected to let this propagate: if the system-native
    dump path also fails, the device is genuinely unreachable and
    retrying in-process will not help.
    """


async def dump_ui_tree(
    serial: str,
    *,
    adb_binary: str = "adb",
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Capture a UI tree from the device via native ``uiautomator dump``.

    Returns a dict in the same shape as ``droidrun.AdbTools.get_state()``
    first-tuple-element, so parsers can consume it without awareness
    of the fallback path.

    Parameters
    ----------
    serial
        ADB device serial. Passed through ``adb -s <serial>``.
    adb_binary
        Path to the ``adb`` executable. Defaults to the PATH-resolved
        ``adb`` used elsewhere in the project.
    timeout_seconds
        Kill the subprocess if it hangs. ``uiautomator dump`` is
        typically ~1-2s on a reachable device.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            adb_binary,
            "-s",
            serial,
            "exec-out",
            "uiautomator",
            "dump",
            "/dev/tty",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise UiAutomatorFallbackError(f"adb binary not found: {adb_binary!r}") from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise UiAutomatorFallbackError(
            f"uiautomator dump timed out after {timeout_seconds}s on {serial}"
        ) from exc

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise UiAutomatorFallbackError(
            f"adb uiautomator dump returned {proc.returncode} on {serial}: {stderr_text}"
        )

    return parse_uiautomator_xml(stdout_bytes)


def parse_uiautomator_xml(raw: bytes) -> dict[str, Any]:
    """Parse a ``uiautomator dump`` XML blob into a tree dict.

    Tolerates trailing status lines ``adb`` sometimes appends after the
    ``</hierarchy>`` close tag (seen on some OEM builds). Raises
    ``UiAutomatorFallbackError`` if the input is empty, contains no
    ``<hierarchy>`` root, or is not well-formed XML.
    """
    if not raw:
        raise UiAutomatorFallbackError("empty uiautomator dump output")

    end_idx = raw.rfind(b"</hierarchy>")
    if end_idx == -1:
        preview = raw[:200].decode("utf-8", errors="replace")
        raise UiAutomatorFallbackError(
            f"no </hierarchy> tag in uiautomator output; got: {preview!r}"
        )
    xml_bytes = raw[: end_idx + len(b"</hierarchy>")]

    try:
        root = ET.fromstring(xml_bytes)  # noqa: S314 - uiautomator output is local device data
    except ET.ParseError as exc:
        raise UiAutomatorFallbackError(f"malformed uiautomator XML: {exc}") from exc

    if root.tag != "hierarchy":
        raise UiAutomatorFallbackError(
            f"expected <hierarchy> root, got <{root.tag}>"
        )

    top_nodes = list(root)
    if not top_nodes:
        # Empty hierarchy — screen is blank. Return a minimal node so
        # downstream parsers see a valid but childless tree.
        return _empty_root()

    if len(top_nodes) == 1:
        return _convert_node(top_nodes[0])

    # Multiple top-level nodes (rare — usually happens if uiautomator
    # reports multiple windows). Wrap them in a synthetic container so
    # the shape stays a single dict, matching DroidRun's convention.
    synthetic = _empty_root()
    synthetic["children"] = [_convert_node(n) for n in top_nodes]
    return synthetic


def _empty_root() -> dict[str, Any]:
    return {
        "resourceId": "",
        "className": "android.widget.FrameLayout",
        "packageName": "",
        "text": "",
        "contentDescription": "",
        "hint": "",
        "stateDescription": "",
        "tooltipText": "",
        "paneTitle": "",
        "error": "",
        "boundsInScreen": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "boundsInParent": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "isClickable": False,
        "isLongClickable": False,
        "isContextClickable": False,
        "isFocusable": False,
        "isFocused": False,
        "isAccessibilityFocused": False,
        "isSelected": False,
        "isCheckable": False,
        "isChecked": False,
        "isEnabled": True,
        "isVisibleToUser": True,
        "isScrollable": False,
        "children": [],
    }


def _convert_node(elem: ET.Element) -> dict[str, Any]:
    attrib = elem.attrib
    bounds = _parse_bounds(attrib.get("bounds", ""))
    node: dict[str, Any] = {
        "resourceId": attrib.get("resource-id", "") or "",
        "className": attrib.get("class", "") or "",
        "packageName": attrib.get("package", "") or "",
        "text": attrib.get("text", "") or "",
        "contentDescription": attrib.get("content-desc", "") or "",
        "hint": "",
        "stateDescription": "",
        "tooltipText": "",
        "paneTitle": "",
        "error": "",
        "boundsInScreen": bounds,
        "boundsInParent": dict(bounds),
        "isClickable": _xml_bool(attrib, "clickable"),
        "isLongClickable": _xml_bool(attrib, "long-clickable"),
        "isContextClickable": False,
        "isFocusable": _xml_bool(attrib, "focusable"),
        "isFocused": _xml_bool(attrib, "focused"),
        "isAccessibilityFocused": False,
        "isSelected": _xml_bool(attrib, "selected"),
        "isCheckable": _xml_bool(attrib, "checkable"),
        "isChecked": _xml_bool(attrib, "checked"),
        "isEnabled": _xml_bool(attrib, "enabled", default=True),
        "isVisibleToUser": True,
        "isScrollable": _xml_bool(attrib, "scrollable"),
        "children": [_convert_node(child) for child in elem],
    }
    return node


def _xml_bool(attrib: dict[str, str], key: str, *, default: bool = False) -> bool:
    raw = attrib.get(key)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def _parse_bounds(raw: str) -> dict[str, int]:
    match = _BOUNDS_RE.search(raw or "")
    if not match:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0}
    left, top, right, bottom = (int(g) for g in match.groups())
    return {"left": left, "top": top, "right": right, "bottom": bottom}
