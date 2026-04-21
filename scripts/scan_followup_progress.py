#!/usr/bin/env python3
"""扫描某台设备的 realtime followup 真实进度。

用法示例（在仓库根目录执行）：

    # 默认 10AEB80XHX006D4，最近 30 分钟
    python scripts/scan_followup_progress.py

    # 指定设备 + 最近 60 分钟
    python scripts/scan_followup_progress.py 9586492623004ZE --minutes 60

    # 指定从某个时刻开始（今天的）
    python scripts/scan_followup_progress.py 10AEB80XHX006D4 --since 20:14

    # 只看错误/警告
    python scripts/scan_followup_progress.py 10AEB80XHX006D4 --errors-only

    # 只看最近 5 轮扫描
    python scripts/scan_followup_progress.py 10AEB80XHX006D4 --tail 5

    # 直接指定日志文件
    python scripts/scan_followup_progress.py --log-path logs/DESKTOP-NIF2DO4-10AEB80XHX006D4.log

脚本只读，不修改任何文件，也不连接数据库 / 设备。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path

DEFAULT_SERIAL = "10AEB80XHX006D4"
DEFAULT_MINUTES = 30

LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\|\s*"
    r"(?P<level>\w+)\s*\|\s*"
    r"(?P<src>[^|]+?)\s*\|\s*"
    r"(?P<msg>.*)$"
)

SCAN_START_RE = re.compile(r"\[Scan #(\d+)\] Checking for unread messages")
SCAN_NO_UNREAD_RE = re.compile(r"\[Scan #(\d+)\] No unread messages")
SCAN_SUMMARY_RE = re.compile(
    r"\[scan_summary\] scan=#(\d+)\s+replies=(\d+)\s+ai_failures=(\d+)\s+"
    r"cb=(\w+)\s+last_error=(.+?)$"
)
SLEEP_RE = re.compile(r"Sleeping (\d+)s until next scan")
PROCESS_START_RE = re.compile(r"FOLLOW-UP PROCESS STARTED FOR (\S+)")
STEP_RE = re.compile(r"Step (\d+):\s*(.+)")
PHASE1_DONE_RE = re.compile(r"PHASE 1 COMPLETE")
SESSION_METRIC_RE = re.compile(r'"event":\s*"session_summary"')


@dataclass
class ScanCycle:
    number: int
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    no_unread: bool = False
    replies: int | None = None
    ai_failures: int | None = None
    cb_state: str | None = None
    last_error: str | None = None
    steps: list[tuple[datetime, str]] = field(default_factory=list)
    has_phase1_complete: bool = False

    @property
    def duration_s(self) -> float | None:
        if self.start_ts and self.end_ts:
            return (self.end_ts - self.start_ts).total_seconds()
        return None


@dataclass
class Findings:
    log_path: Path
    file_size_bytes: int
    lines_total: int
    lines_in_window: int
    window_start: datetime | None
    window_end: datetime | None
    process_starts: list[datetime] = field(default_factory=list)
    scans: dict[int, ScanCycle] = field(default_factory=dict)
    last_session_summary: dict | None = None
    errors: list[tuple[datetime, str, str]] = field(default_factory=list)
    warnings: list[tuple[datetime, str, str]] = field(default_factory=list)
    sleeps: list[tuple[datetime, int]] = field(default_factory=list)
    last_log_ts: datetime | None = None


def parse_ts(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def find_log_path(project_root: Path, serial: str) -> Path | None:
    """Find the active (non-rotated) log file for a serial under logs/.

    The current file looks like ``<HOST>-<SERIAL>.log``; rotated files have an
    extra ``.YYYY-MM-DD_HH-MM-SS_NNNNNN.log`` suffix.
    """
    logs_dir = project_root / "logs"
    if not logs_dir.exists():
        return None
    candidates = [
        p
        for p in logs_dir.glob(f"*-{serial}.log")
        if p.is_file() and "_" not in p.stem.split("-", 2)[-1]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def resolve_window(
    minutes: int | None,
    since: str | None,
    file_mtime: datetime,
) -> datetime | None:
    """Return the lower bound for the inspection window, or None for ``--all``."""
    if since is not None:
        try:
            t = time.fromisoformat(since)
        except ValueError:
            print(f"[ERROR] --since must be HH:MM[:SS], got {since!r}", file=sys.stderr)
            sys.exit(2)
        anchor_date = file_mtime.date()
        candidate = datetime.combine(anchor_date, t)
        # If the resolved time is after the file's last write, it's the previous day.
        if candidate > file_mtime:
            candidate -= timedelta(days=1)
        return candidate
    if minutes is not None:
        return file_mtime - timedelta(minutes=minutes)
    return None


def collect_findings(
    log_path: Path,
    window_start: datetime | None,
) -> Findings:
    text_size = log_path.stat().st_size
    findings = Findings(
        log_path=log_path,
        file_size_bytes=text_size,
        lines_total=0,
        lines_in_window=0,
        window_start=window_start,
        window_end=None,
    )

    current_scan: ScanCycle | None = None

    with log_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            findings.lines_total += 1
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = parse_ts(m.group("ts"))
            if ts is None:
                continue
            if window_start and ts < window_start:
                continue

            findings.lines_in_window += 1
            findings.last_log_ts = ts
            if findings.window_end is None or ts > findings.window_end:
                findings.window_end = ts

            level = m.group("level").strip()
            msg = m.group("msg")

            if PROCESS_START_RE.search(msg):
                findings.process_starts.append(ts)

            if (sm := SCAN_START_RE.search(msg)) is not None:
                num = int(sm.group(1))
                current_scan = findings.scans.setdefault(num, ScanCycle(number=num))
                current_scan.start_ts = ts
                continue

            if (sm := SCAN_NO_UNREAD_RE.search(msg)) is not None:
                num = int(sm.group(1))
                cycle = findings.scans.setdefault(num, ScanCycle(number=num))
                cycle.no_unread = True
                cycle.end_ts = ts
                continue

            if (sm := SCAN_SUMMARY_RE.search(msg)) is not None:
                num = int(sm.group(1))
                cycle = findings.scans.setdefault(num, ScanCycle(number=num))
                cycle.replies = int(sm.group(2))
                cycle.ai_failures = int(sm.group(3))
                cycle.cb_state = sm.group(4)
                cycle.last_error = sm.group(5).strip()
                cycle.end_ts = ts
                continue

            if PHASE1_DONE_RE.search(msg):
                if current_scan is not None:
                    current_scan.has_phase1_complete = True
                continue

            if (sm := SLEEP_RE.search(msg)) is not None:
                findings.sleeps.append((ts, int(sm.group(1))))
                continue

            if SESSION_METRIC_RE.search(msg):
                try:
                    payload = json.loads(msg)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    findings.last_session_summary = payload
                continue

            if (sm := STEP_RE.search(msg)) is not None and current_scan is not None:
                current_scan.steps.append((ts, f"Step {sm.group(1)}: {sm.group(2)}"))
                continue

            if level == "ERROR":
                findings.errors.append((ts, level, msg.strip()))
            elif level == "WARNING":
                findings.warnings.append((ts, level, msg.strip()))

    return findings


def fmt_ts(ts: datetime | None) -> str:
    return ts.strftime("%H:%M:%S") if ts else "---"


def fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "  ?  "
    return f"{seconds:6.1f}s"


def render_report(findings: Findings, *, tail: int | None, errors_only: bool) -> str:
    lines: list[str] = []
    rel_path = findings.log_path
    lines.append("=" * 72)
    lines.append(f" Followup progress  ::  {rel_path}")
    lines.append("=" * 72)
    size_kb = findings.file_size_bytes / 1024
    win_lo = fmt_ts(findings.window_start) if findings.window_start else "<begin>"
    win_hi = fmt_ts(findings.window_end) if findings.window_end else "<empty>"
    lines.append(
        f" file: {size_kb:,.1f} KB   "
        f"lines total={findings.lines_total:,}   in-window={findings.lines_in_window:,}"
    )
    lines.append(f" window: {win_lo}  →  {win_hi}")
    if findings.last_log_ts:
        idle = (datetime.now() - findings.last_log_ts).total_seconds()
        lines.append(
            f" last log entry: {findings.last_log_ts:%Y-%m-%d %H:%M:%S} "
            f"(~{idle:.0f}s ago)"
        )
    lines.append("")

    if findings.process_starts:
        lines.append(" Process restarts in window:")
        for ts in findings.process_starts:
            lines.append(f"   * {ts:%Y-%m-%d %H:%M:%S}")
        lines.append("")

    if not errors_only:
        scans_sorted = sorted(
            findings.scans.values(),
            key=lambda c: (c.start_ts or c.end_ts or datetime.min, c.number),
        )
        if tail is not None:
            scans_sorted = scans_sorted[-tail:]
        if scans_sorted:
            replies_total = sum(c.replies or 0 for c in scans_sorted)
            ai_fail_total = sum(c.ai_failures or 0 for c in scans_sorted)
            no_unread_count = sum(1 for c in scans_sorted if c.no_unread)
            lines.append(
                f" Scans shown: {len(scans_sorted)}   "
                f"replies={replies_total}   "
                f"ai_failures={ai_fail_total}   "
                f"no-unread cycles={no_unread_count}"
            )
            cb_states = Counter(c.cb_state for c in scans_sorted if c.cb_state)
            if cb_states:
                cb_str = ", ".join(f"{k}={v}" for k, v in cb_states.most_common())
                lines.append(f" Circuit breaker states: {cb_str}")
            lines.append("")
            lines.append(
                f"  {'scan#':>6}  {'start':>8}  {'dur':>7}  "
                f"{'unread?':>8}  {'reply':>5}  {'aifail':>6}  {'cb':<8}  last_error"
            )
            lines.append("  " + "-" * 70)
            for c in scans_sorted:
                lines.append(
                    f"  {c.number:>6}  {fmt_ts(c.start_ts):>8}  "
                    f"{fmt_dur(c.duration_s):>7}  "
                    f"{('yes' if not c.no_unread else 'no'):>8}  "
                    f"{(c.replies if c.replies is not None else '-'):>5}  "
                    f"{(c.ai_failures if c.ai_failures is not None else '-'):>6}  "
                    f"{(c.cb_state or '-'):<8}  "
                    f"{(c.last_error or '-')[:30]}"
                )
            lines.append("")

            unfinished = [c for c in scans_sorted if c.start_ts and not c.end_ts]
            if unfinished:
                lines.append(" Unfinished scans (started, no summary yet):")
                for c in unfinished:
                    lines.append(
                        f"   * #{c.number} started {fmt_ts(c.start_ts)} – "
                        f"steps so far: {len(c.steps)}"
                    )
                    for ts, label in c.steps[-5:]:
                        lines.append(f"       {fmt_ts(ts)}  {label}")
                lines.append("")

        if findings.sleeps:
            last_sleep_ts, last_sleep_s = findings.sleeps[-1]
            lines.append(
                f" Last sleep gap: {last_sleep_s}s "
                f"(announced at {fmt_ts(last_sleep_ts)})"
            )
            lines.append("")

        if findings.last_session_summary:
            data = findings.last_session_summary.get("data", {})
            ts_str = findings.last_session_summary.get("timestamp", "?")
            lines.append(f" Last session_summary @ {ts_str}")
            for key in (
                "duration_seconds",
                "total_messages",
                "messages_added",
                "ai_replies_generated",
                "ai_replies_sent",
                "ai_replies_failed",
                "blacklist_additions",
                "errors",
                "total_customers",
                "engaged_customers",
                "engagement_rate",
            ):
                if key in data:
                    lines.append(f"   {key:>22} = {data[key]}")
            lines.append("")

    if findings.warnings:
        warn_count = Counter(w[2].split("|")[0].strip() for w in findings.warnings)
        lines.append(f" WARNINGS in window: {len(findings.warnings)}")
        for sample, n in warn_count.most_common(5):
            lines.append(f"   x{n}  {sample[:90]}")
        lines.append("")

    if findings.errors:
        lines.append(f" ERRORS in window: {len(findings.errors)}")
        for ts, _level, msg in findings.errors[-10:]:
            lines.append(f"   {fmt_ts(ts)}  {msg[:120]}")
    elif not errors_only:
        lines.append(" ERRORS in window: 0")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "serial",
        nargs="?",
        default=DEFAULT_SERIAL,
        help=f"Device serial (default: {DEFAULT_SERIAL})",
    )
    window = parser.add_mutually_exclusive_group()
    window.add_argument(
        "--minutes",
        type=int,
        default=DEFAULT_MINUTES,
        help=f"Only inspect the last N minutes of the log (default: {DEFAULT_MINUTES}).",
    )
    window.add_argument(
        "--since",
        type=str,
        help="Inspect from HH:MM[:SS] of the most recent log day onwards.",
    )
    window.add_argument(
        "--all",
        action="store_true",
        help="Inspect the entire log file.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=None,
        help="Limit the per-scan table to the last N scans.",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Only print errors/warnings sections.",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Explicit path to the log file (overrides serial autodetect).",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    if args.log_path is not None:
        log_path = args.log_path
        if not log_path.is_absolute():
            log_path = project_root / log_path
    else:
        found = find_log_path(project_root, args.serial)
        if found is None:
            print(
                f"[ERROR] No active log file found for serial {args.serial!r} "
                f"under {project_root / 'logs'}",
                file=sys.stderr,
            )
            return 1
        log_path = found

    if not log_path.exists():
        print(f"[ERROR] Log file does not exist: {log_path}", file=sys.stderr)
        return 1

    file_mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
    window_start = (
        None
        if args.all
        else resolve_window(
            minutes=None if args.since else args.minutes,
            since=args.since,
            file_mtime=file_mtime,
        )
    )

    findings = collect_findings(log_path, window_start=window_start)

    print(render_report(findings, tail=args.tail, errors_only=args.errors_only))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
