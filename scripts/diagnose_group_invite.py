"""
Diagnostic script for auto-group-invite across multiple phone models.

Connects to all ADB-connected devices, collects device metadata,
WeCom version, DroidRun Portal status, and dumps the UI tree at
the current screen. Produces a structured comparison report.

Usage:
    uv run python scripts/diagnose_group_invite.py
"""

from __future__ import annotations

import asyncio
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "diagnostic_reports"


def _run_adb(args: list[str], adb_path: str = "adb") -> str:
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        [adb_path, *args],
        capture_output=True,
        timeout=30,
        **kwargs,
    )
    return result.stdout.decode("utf-8", errors="replace")


def _run_adb_shell(serial: str, *cmd: str, adb_path: str = "adb") -> str:
    return _run_adb(["-s", serial, "shell", *cmd], adb_path=adb_path)


def get_adb_path() -> str:
    project_adb = PROJECT_ROOT / "wecom-desktop" / "adb" / "adb.exe"
    if project_adb.exists():
        return str(project_adb)
    project_adb2 = PROJECT_ROOT / "wecom-desktop" / "scrcpy" / "adb.exe"
    if project_adb2.exists():
        return str(project_adb2)
    found = shutil.which("adb")
    return found or "adb"


def list_devices(adb_path: str) -> list[dict]:
    raw = _run_adb(["devices", "-l"], adb_path=adb_path)
    devices = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("List of") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        extras = {}
        for token in parts[2:]:
            if ":" in token:
                k, v = token.split(":", 1)
                extras[k] = v
        devices.append({"serial": serial, "state": state, **extras})
    return devices


def get_device_info(serial: str, adb_path: str) -> dict:
    info: dict = {"serial": serial}
    props_raw = _run_adb_shell(serial, "getprop", adb_path=adb_path)
    props = {}
    for line in props_raw.splitlines():
        line = line.strip()
        if not line.startswith("[") or "]: [" not in line:
            continue
        try:
            key_part, val_part = line.split("]:", 1)
        except ValueError:
            continue
        key = key_part.strip("[]")
        val = val_part.strip().strip("[]")
        props[key] = val

    info["manufacturer"] = props.get("ro.product.manufacturer", "unknown")
    info["brand"] = props.get("ro.product.brand", "unknown")
    info["model"] = props.get("ro.product.model", "unknown")
    info["android_version"] = props.get("ro.build.version.release", "unknown")
    info["sdk_version"] = props.get("ro.build.version.sdk", "unknown")

    size_raw = _run_adb_shell(serial, "wm", "size", adb_path=adb_path)
    m = re.search(r"Physical size:\s*(\d+x\d+)", size_raw)
    info["screen_resolution"] = m.group(1) if m else "unknown"

    density_raw = _run_adb_shell(serial, "wm", "density", adb_path=adb_path)
    m = re.search(r"Physical density:\s*(\d+)", density_raw)
    info["screen_density"] = m.group(1) if m else "unknown"

    wecom_raw = _run_adb_shell(
        serial,
        "dumpsys",
        "package",
        "com.tencent.wework",
        adb_path=adb_path,
    )
    m = re.search(r"versionName=([^\s]+)", wecom_raw)
    info["wecom_version"] = m.group(1) if m else "unknown"
    m = re.search(r"versionCode=(\d+)", wecom_raw)
    info["wecom_version_code"] = m.group(1) if m else "unknown"

    return info


def check_accessibility_services(serial: str, adb_path: str) -> dict:
    raw = _run_adb_shell(
        serial,
        "settings",
        "get",
        "secure",
        "enabled_accessibility_services",
        adb_path=adb_path,
    )
    services = raw.strip()
    has_droidrun = "droidrun" in services.lower() or "portal" in services.lower()
    return {
        "enabled_services": services,
        "droidrun_portal_enabled": has_droidrun,
    }


def dump_ui_tree_via_uiautomator(serial: str, adb_path: str) -> str | None:
    """Fallback: dump UI hierarchy via uiautomator (may conflict with DroidRun)."""
    try:
        _run_adb_shell(serial, "uiautomator", "dump", "/sdcard/ui_dump.xml", adb_path=adb_path)
        raw = _run_adb_shell(serial, "cat", "/sdcard/ui_dump.xml", adb_path=adb_path)
        _run_adb_shell(serial, "rm", "/sdcard/ui_dump.xml", adb_path=adb_path)
        return raw
    except Exception as exc:
        return f"ERROR: {exc}"


async def dump_ui_tree_via_droidrun(serial: str, port: int = 8080) -> dict | None:
    """Dump UI tree via DroidRun AdbTools (preferred, non-destructive)."""
    try:
        from droidrun import AdbTools

        adb = AdbTools(serial=serial, use_tcp=True, remote_tcp_port=port)
        await adb.get_state()
        raw_tree = getattr(adb, "raw_tree_cache", None)
        clickable = getattr(adb, "clickable_elements_cache", [])
        return {
            "raw_tree": raw_tree,
            "clickable_elements": clickable,
            "clickable_count": len(clickable),
        }
    except Exception as exc:
        return {"error": str(exc)}


def extract_resource_ids(tree, prefix: str = "") -> list[dict]:
    """Recursively extract all resource IDs, text, bounds, and class from a UI tree."""
    results = []
    if not isinstance(tree, dict):
        return results

    entry = {
        "resourceId": tree.get("resourceId", ""),
        "className": tree.get("className", ""),
        "text": tree.get("text", ""),
        "contentDescription": tree.get("contentDescription", ""),
        "bounds": tree.get("bounds") or tree.get("boundsInScreen", ""),
        "clickable": tree.get("clickable", False) or tree.get("isClickable", False),
        "index": tree.get("index"),
    }
    if entry["resourceId"] or entry["text"] or entry["contentDescription"]:
        results.append(entry)

    for child in tree.get("children", []):
        results.extend(extract_resource_ids(child))
    return results


def extract_all_resource_id_suffixes(elements: list[dict]) -> set[str]:
    suffixes = set()
    for el in elements:
        rid = el.get("resourceId", "")
        if rid and ":" in rid:
            suffix = rid.split(":")[-1].split("/")[-1]
            if suffix:
                suffixes.add(suffix)
        elif rid:
            suffixes.add(rid)
    return suffixes


def analyze_group_invite_readiness(elements: list[dict]) -> dict:
    """Check whether group-invite-relevant UI elements can be found."""
    from wecom_automation.services.group_invite import selectors

    def find_by_patterns(text_pats, desc_pats, res_pats):
        found = []
        for el in elements:
            text = (el.get("text") or "").lower()
            desc = (el.get("contentDescription") or "").lower()
            rid = (el.get("resourceId") or "").lower()
            if (
                any(p.lower() in text for p in text_pats)
                or any(p.lower() in desc for p in desc_pats)
                or any(p.lower() in rid for p in res_pats)
            ):
                found.append(el)
        return found

    return {
        "chat_info_menu": find_by_patterns(
            selectors.CHAT_INFO_MENU_TEXT_PATTERNS,
            selectors.CHAT_INFO_MENU_DESC_PATTERNS,
            selectors.CHAT_INFO_MENU_RESOURCE_PATTERNS,
        ),
        "add_member": find_by_patterns(
            selectors.ADD_MEMBER_TEXT_PATTERNS,
            selectors.ADD_MEMBER_DESC_PATTERNS,
            selectors.ADD_MEMBER_RESOURCE_PATTERNS,
        ),
        "search": find_by_patterns(
            selectors.SEARCH_TEXT_PATTERNS,
            selectors.SEARCH_DESC_PATTERNS,
            selectors.SEARCH_RESOURCE_PATTERNS,
        ),
        "confirm_group": find_by_patterns(
            selectors.CONFIRM_GROUP_TEXT_PATTERNS,
            selectors.CONFIRM_GROUP_DESC_PATTERNS,
            selectors.CONFIRM_GROUP_RESOURCE_PATTERNS,
        ),
    }


KNOWN_MEDIA_RESOURCE_IDS = {
    "timestamp": ["ief", "ih1"],
    "video_duration": ["e5v", "e5l", "e8l"],
    "video_thumbnail": ["k2j", "k1r", "k1s"],
    "play_button": ["jqb", "jpn"],
    "sticker": ["igf", "ijr"],
    "avatar": ["im4", "ilg", "iov"],
    "voice_duration": ["ies"],
    "text_content": ["idk"],
    "message_bubble": ["hwl", "ih3"],
    "message_row": ["cmn"],
    "voice_transcription": ["p05"],
}


def check_media_resource_ids(all_suffixes: set[str]) -> dict:
    """Check which known media resource IDs are present on this device."""
    report = {}
    for category, known_ids in KNOWN_MEDIA_RESOURCE_IDS.items():
        found = [rid for rid in known_ids if rid in all_suffixes]
        missing = [rid for rid in known_ids if rid not in all_suffixes]
        report[category] = {"found": found, "missing": missing}
    return report


def generate_comparison_report(device_reports: list[dict]) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append("AUTO-GROUP-INVITE MULTI-DEVICE DIAGNOSTIC REPORT")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("=" * 80)

    lines.append("\n## DEVICE SUMMARY\n")
    for i, dr in enumerate(device_reports):
        info = dr["device_info"]
        lines.append(f"### Device {i + 1}: {info['model']} ({info['serial']})")
        lines.append(f"  Manufacturer: {info['manufacturer']} / Brand: {info['brand']}")
        lines.append(f"  Android: {info['android_version']} (SDK {info['sdk_version']})")
        lines.append(f"  Screen: {info['screen_resolution']} @ {info['screen_density']}dpi")
        lines.append(f"  WeCom: {info['wecom_version']} (code {info['wecom_version_code']})")

        acc = dr.get("accessibility", {})
        portal_ok = acc.get("droidrun_portal_enabled", False)
        status = "ENABLED" if portal_ok else "NOT FOUND / DISABLED"
        lines.append(f"  DroidRun Portal: {status}")
        lines.append(f"  Accessibility services: {acc.get('enabled_services', 'N/A')}")
        lines.append("")

    lines.append("\n## SCREEN RESOLUTION COMPARISON\n")
    resolutions = set()
    for dr in device_reports:
        res = dr["device_info"]["screen_resolution"]
        resolutions.add(res)
        lines.append(f"  {dr['device_info']['model']}: {res}")
    if len(resolutions) > 1:
        lines.append("\n  *** WARNING: Multiple resolutions detected! Hardcoded pixel bounds will fail. ***")
    else:
        lines.append("\n  All devices share the same resolution.")

    lines.append("\n## WECOM VERSION COMPARISON\n")
    versions = set()
    for dr in device_reports:
        ver = dr["device_info"]["wecom_version"]
        versions.add(ver)
        lines.append(f"  {dr['device_info']['model']}: {ver}")
    if len(versions) > 1:
        lines.append("\n  *** WARNING: Multiple WeCom versions! Resource IDs likely differ. ***")
    else:
        lines.append("\n  All devices run the same WeCom version.")

    lines.append("\n## RESOURCE ID ANALYSIS\n")
    for category, known_ids in KNOWN_MEDIA_RESOURCE_IDS.items():
        lines.append(f"### {category} (known IDs: {known_ids})")
        for dr in device_reports:
            media_check = dr.get("media_resource_ids", {}).get(category, {})
            found = media_check.get("found", [])
            missing = media_check.get("missing", known_ids)
            model = dr["device_info"]["model"]
            if found:
                lines.append(f"  {model}: FOUND {found}")
            else:
                lines.append(f"  {model}: NONE FOUND (all missing: {missing})")
        lines.append("")

    lines.append("\n## UNKNOWN RESOURCE IDS (per device)\n")
    lines.append("Resource IDs found on device but NOT in known patterns (potential new WeCom IDs):\n")
    all_known = set()
    for ids_list in KNOWN_MEDIA_RESOURCE_IDS.values():
        all_known.update(ids_list)

    for dr in device_reports:
        model = dr["device_info"]["model"]
        suffixes = dr.get("all_resource_id_suffixes", set())
        unknown = sorted(suffixes - all_known)
        lines.append(f"  {model}: {len(unknown)} unknown IDs")
        if unknown:
            for uid in unknown[:50]:
                lines.append(f"    - {uid}")
            if len(unknown) > 50:
                lines.append(f"    ... and {len(unknown) - 50} more")
        lines.append("")

    lines.append("\n## GROUP INVITE SELECTOR MATCHES (current screen)\n")
    for dr in device_reports:
        model = dr["device_info"]["model"]
        gi = dr.get("group_invite_readiness", {})
        lines.append(f"### {model}")
        for step, matches in gi.items():
            count = len(matches)
            status_str = f"FOUND ({count})" if count > 0 else "NOT FOUND"
            lines.append(f"  {step}: {status_str}")
            for m in matches[:3]:
                lines.append(
                    f"    text={m.get('text')!r}, desc={m.get('contentDescription')!r}, "
                    f"rid={m.get('resourceId')!r}, bounds={m.get('bounds')!r}"
                )
        lines.append("")

    lines.append("\n## UI TREE STATS\n")
    for dr in device_reports:
        model = dr["device_info"]["model"]
        tree_data = dr.get("ui_tree_droidrun", {})
        if "error" in tree_data:
            lines.append(f"  {model}: DroidRun ERROR - {tree_data['error']}")
        else:
            lines.append(f"  {model}: {tree_data.get('clickable_count', 'N/A')} clickable elements")
        all_els = dr.get("all_elements", [])
        lines.append(f"  {model}: {len(all_els)} total elements with resourceId/text/desc")
        lines.append("")

    lines.append("\n## DROIDRUN PORTAL STATUS\n")
    for dr in device_reports:
        model = dr["device_info"]["model"]
        acc = dr.get("accessibility", {})
        if acc.get("droidrun_portal_enabled"):
            lines.append(f"  {model}: OK")
        else:
            lines.append(f"  {model}: *** PORTAL NOT ENABLED - group invite will fail ***")
            lines.append("    Fix: Re-enable DroidRun Portal accessibility service on this device")
    lines.append("")

    lines.append("\n## RECOMMENDATIONS\n")
    if len(versions) > 1:
        lines.append("  1. WeCom versions differ - update ui_parser.py resource IDs for each version")
    if len(resolutions) > 1:
        lines.append("  2. Screen resolutions differ - add resolution-aware scaling to bounds checks")
    for dr in device_reports:
        if not dr.get("accessibility", {}).get("droidrun_portal_enabled"):
            lines.append(f"  3. Re-enable DroidRun Portal on {dr['device_info']['model']}")

    lines.append("\n" + "=" * 80)
    return "\n".join(lines)


async def diagnose_device(serial: str, adb_path: str, port: int = 8080) -> dict:
    print(f"\n--- Diagnosing device: {serial} ---")

    print("  Collecting device info...")
    device_info = get_device_info(serial, adb_path)
    print(
        f"  Model: {device_info['model']}, Android: {device_info['android_version']}, "
        f"WeCom: {device_info['wecom_version']}, Screen: {device_info['screen_resolution']}"
    )

    print("  Checking accessibility services...")
    accessibility = check_accessibility_services(serial, adb_path)
    print(f"  DroidRun Portal: {'ENABLED' if accessibility['droidrun_portal_enabled'] else 'NOT FOUND'}")

    print("  Dumping UI tree via DroidRun...")
    ui_tree_droidrun = await dump_ui_tree_via_droidrun(serial, port)

    all_elements: list[dict] = []
    all_suffixes: set[str] = set()
    if ui_tree_droidrun and "error" not in ui_tree_droidrun:
        raw_tree = ui_tree_droidrun.get("raw_tree")
        if raw_tree:
            all_elements = extract_resource_ids(raw_tree)
            all_suffixes = extract_all_resource_id_suffixes(all_elements)
        clickable = ui_tree_droidrun.get("clickable_elements", [])
        for el in clickable:
            all_elements.extend(extract_resource_ids(el) if isinstance(el, dict) else [])
            rid = el.get("resourceId") or ""
            if rid:
                suffix = rid.split(":")[-1].split("/")[-1] if ":" in rid else rid
                all_suffixes.add(suffix)
    else:
        print("  DroidRun failed, trying uiautomator fallback...")
        ui_xml = dump_ui_tree_via_uiautomator(serial, adb_path)
        if ui_xml and not ui_xml.startswith("ERROR"):
            for m in re.finditer(r'resource-id="([^"]*)"', ui_xml):
                rid = m.group(1)
                suffix = rid.split("/")[-1] if "/" in rid else rid
                all_suffixes.add(suffix)
                all_elements.append({"resourceId": rid})
            for m in re.finditer(r'text="([^"]*)"', ui_xml):
                all_elements.append({"text": m.group(1)})

    media_resource_ids = check_media_resource_ids(all_suffixes)

    gi_readiness = {}
    try:
        gi_readiness = analyze_group_invite_readiness(all_elements)
    except Exception as exc:
        gi_readiness = {"error": str(exc)}

    return {
        "device_info": device_info,
        "accessibility": accessibility,
        "ui_tree_droidrun": ui_tree_droidrun or {},
        "all_elements": all_elements,
        "all_resource_id_suffixes": all_suffixes,
        "media_resource_ids": media_resource_ids,
        "group_invite_readiness": gi_readiness,
    }


async def main():
    adb_path = get_adb_path()
    print(f"Using ADB: {adb_path}")

    devices = list_devices(adb_path)
    online = [d for d in devices if d.get("state") == "device"]

    if not online:
        print("\nERROR: No online devices found. Please connect phones via USB and enable USB debugging.")
        sys.exit(1)

    print(f"\nFound {len(online)} online device(s):")
    for d in online:
        print(f"  {d['serial']} (model={d.get('model', 'unknown')})")

    device_reports = []
    for d in online:
        serial = d["serial"]
        report = await diagnose_device(serial, adb_path)
        device_reports.append(report)

    comparison = generate_comparison_report(device_reports)
    print("\n" + comparison)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"group_invite_diagnosis_{timestamp}.txt"
    report_path.write_text(comparison, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    raw_data_path = REPORT_DIR / f"group_invite_raw_{timestamp}.json"

    def serialize(obj):
        if isinstance(obj, set):
            return sorted(obj)
        return str(obj)

    raw_data_path.write_text(
        json.dumps(device_reports, indent=2, ensure_ascii=False, default=serialize),
        encoding="utf-8",
    )
    print(f"Raw data saved to: {raw_data_path}")


if __name__ == "__main__":
    asyncio.run(main())
