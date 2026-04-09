from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def get_process_memory_mb() -> float | None:
    """Best-effort resident memory usage in MB."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        if ok:
            return round(counters.WorkingSetSize / 1024 / 1024, 2)
    except Exception:
        pass

    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = getattr(usage, "ru_maxrss", 0)
        if rss <= 0:
            return None
        if rss > 1024 * 1024:
            return round(rss / 1024 / 1024, 2)
        return round(rss / 1024, 2)
    except Exception:
        return None


class PerformanceMetrics:
    """Thread-safe in-memory runtime metrics with lightweight JSONL flushing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._startup_started_at = time.perf_counter()
        self._startup_completed_at: str | None = None
        self._startup_duration_ms: float | None = None
        self._startup_memory_mb: float | None = None
        self._adb_calls_total = 0
        self._adb_cached_hits = 0
        self._adb_calls_by_kind: dict[str, dict[str, float | int]] = {}
        self._poll_counts: dict[str, int] = {}
        self._poll_last_intervals_ms: dict[str, float] = {}
        self._sync_runs: deque[dict[str, Any]] = deque(maxlen=20)
        self._sqlite_total_queries = 0
        self._sqlite_total_duration_ms = 0.0
        self._sqlite_slow_queries = 0
        self._sqlite_recent_slow_queries: deque[dict[str, Any]] = deque(maxlen=20)
        self._sqlite_max_query_ms = 0.0
        self._metrics_dir: Path | None = None

    def set_metrics_dir(self, metrics_dir: Path) -> None:
        metrics_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._metrics_dir = metrics_dir

    def mark_startup_complete(self) -> None:
        with self._lock:
            if self._startup_completed_at is not None:
                return
            self._startup_completed_at = _utc_now_iso()
            self._startup_duration_ms = round((time.perf_counter() - self._startup_started_at) * 1000, 2)
            self._startup_memory_mb = get_process_memory_mb()
            self._append_jsonl_locked(
                "startup.jsonl",
                {
                    "timestamp": self._startup_completed_at,
                    "startup_duration_ms": self._startup_duration_ms,
                    "startup_memory_mb": self._startup_memory_mb,
                },
            )

    def record_adb_call(self, kind: str, duration_ms: float, *, cached: bool = False) -> None:
        with self._lock:
            self._adb_calls_total += 1
            if cached:
                self._adb_cached_hits += 1
            bucket = self._adb_calls_by_kind.setdefault(kind, {"count": 0, "total_duration_ms": 0.0, "max_ms": 0.0})
            bucket["count"] = int(bucket["count"]) + 1
            bucket["total_duration_ms"] = round(float(bucket["total_duration_ms"]) + duration_ms, 2)
            bucket["max_ms"] = round(max(float(bucket["max_ms"]), duration_ms), 2)

    def record_poll(self, name: str, interval_ms: float) -> None:
        with self._lock:
            self._poll_counts[name] = self._poll_counts.get(name, 0) + 1
            self._poll_last_intervals_ms[name] = round(interval_ms, 2)

    def record_sync_run(
        self,
        serial: str,
        *,
        status: str,
        duration_ms: float | None,
        customers_synced: int | None = None,
        messages_added: int | None = None,
    ) -> None:
        item = {
            "timestamp": _utc_now_iso(),
            "serial": serial,
            "status": status,
            "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
            "customers_synced": customers_synced,
            "messages_added": messages_added,
        }
        with self._lock:
            self._sync_runs.append(item)
            self._append_jsonl_locked("sync-runs.jsonl", item)

    def record_sql_query(self, statement: str, duration_ms: float, *, params_count: int = 0) -> None:
        normalized = " ".join((statement or "").split())
        truncated = normalized[:240]
        with self._lock:
            self._sqlite_total_queries += 1
            self._sqlite_total_duration_ms = round(self._sqlite_total_duration_ms + duration_ms, 2)
            self._sqlite_max_query_ms = round(max(self._sqlite_max_query_ms, duration_ms), 2)
            if duration_ms >= 50:
                self._sqlite_slow_queries += 1
                item = {
                    "timestamp": _utc_now_iso(),
                    "duration_ms": round(duration_ms, 2),
                    "statement": truncated,
                    "params_count": params_count,
                }
                self._sqlite_recent_slow_queries.append(item)
                self._append_jsonl_locked("sqlite-slow.jsonl", item)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            adb_by_kind = {}
            for kind, stats in self._adb_calls_by_kind.items():
                count = int(stats["count"])
                total = float(stats["total_duration_ms"])
                adb_by_kind[kind] = {
                    "count": count,
                    "total_duration_ms": round(total, 2),
                    "avg_duration_ms": round(total / count, 2) if count else 0.0,
                    "max_duration_ms": round(float(stats["max_ms"]), 2),
                }

            sync_runs = list(self._sync_runs)
            completed_durations = [float(run["duration_ms"]) for run in sync_runs if run.get("duration_ms") is not None]

            return {
                "startup": {
                    "completed_at": self._startup_completed_at,
                    "duration_ms": self._startup_duration_ms,
                    "memory_mb": self._startup_memory_mb,
                },
                "runtime": {
                    "memory_mb": get_process_memory_mb(),
                },
                "adb": {
                    "total_calls": self._adb_calls_total,
                    "cached_hits": self._adb_cached_hits,
                    "calls_by_kind": adb_by_kind,
                },
                "polling": {
                    "counts": dict(self._poll_counts),
                    "last_intervals_ms": dict(self._poll_last_intervals_ms),
                },
                "sync": {
                    "recent_runs": sync_runs,
                    "completed_runs": len(completed_durations),
                    "avg_duration_ms": round(sum(completed_durations) / len(completed_durations), 2)
                    if completed_durations
                    else None,
                },
                "sqlite": {
                    "total_queries": self._sqlite_total_queries,
                    "total_duration_ms": round(self._sqlite_total_duration_ms, 2),
                    "slow_queries": self._sqlite_slow_queries,
                    "max_query_ms": round(self._sqlite_max_query_ms, 2),
                    "recent_slow_queries": list(self._sqlite_recent_slow_queries),
                },
            }

    def _append_jsonl_locked(self, filename: str, payload: dict[str, Any]) -> None:
        if self._metrics_dir is None:
            return
        try:
            path = self._metrics_dir / filename
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass


runtime_metrics = PerformanceMetrics()


class InstrumentedCursor(sqlite3.Cursor):
    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        started = time.perf_counter()
        try:
            return super().execute(sql, parameters)
        finally:
            runtime_metrics.record_sql_query(sql, (time.perf_counter() - started) * 1000, params_count=_param_count(parameters))

    def executemany(self, sql: str, seq_of_parameters: Any, /) -> sqlite3.Cursor:
        started = time.perf_counter()
        try:
            return super().executemany(sql, seq_of_parameters)
        finally:
            runtime_metrics.record_sql_query(sql, (time.perf_counter() - started) * 1000)

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        started = time.perf_counter()
        try:
            return super().executescript(sql_script)
        finally:
            runtime_metrics.record_sql_query(sql_script, (time.perf_counter() - started) * 1000)


class InstrumentedConnection(sqlite3.Connection):
    def cursor(self, factory: type[sqlite3.Cursor] | None = None) -> sqlite3.Cursor:
        return super().cursor(factory or InstrumentedCursor)


def _param_count(parameters: Any) -> int:
    try:
        return len(parameters)
    except Exception:
        return 0
