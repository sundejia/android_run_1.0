"""
Runtime hygiene utilities for the WeCom Desktop backend.

This module owns the "make sure the second day still works" responsibilities
that previously had no home:

* **PID-file tracking** for subprocesses spawned by the realtime/sync managers.
  Each spawn writes ``logs/runtime/<kind>-<serial>.pid`` and removes it on a
  graceful stop. On crash/kill the file persists so the next startup can find
  the orphan and kill it.
* **Orphan sweep on startup** — scan PID files for processes that are still
  alive but whose parent is not the current backend (i.e. survivors of a
  previous crash). Also scan the process list for stray
  ``realtime_reply_process.py`` / ``droidrun`` / ``scrcpy`` whose parent is
  PID 1 and matches our project root.
* **Filesystem hygiene** — sweep stale ``wecom-upload-*.db`` files left in
  ``$TMPDIR`` by ``log_upload_service``, and emit a structured summary of
  long-lived artifact directories so operators notice when they balloon.
* **ADB baseline reset** — best-effort ``adb kill-server && adb start-server``
  so we never inherit a wedged daemon from a previous session.

Everything here is **best-effort**: any single step that fails is logged and
swallowed — startup must still succeed even if the host environment is
unusual (no psutil, no adb on PATH, read-only ``$TMPDIR``, etc.).

Intended use::

    # main.py lifespan startup
    from services.runtime_hygiene import startup_hygiene
    summary = await startup_hygiene()
    print(f"[startup] [OK] runtime hygiene: {summary}")

    # realtime_reply_manager spawn / stop
    from services.runtime_hygiene import register_child_pid, unregister_child_pid
    register_child_pid("realtime_reply", serial, pid=process.pid)
    ...
    unregister_child_pid("realtime_reply", serial)
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utils.path_utils import get_project_root

logger = logging.getLogger(__name__)

PROJECT_ROOT = get_project_root()
RUNTIME_DIR = PROJECT_ROOT / "logs" / "runtime"

# How old a leftover wecom-upload-*.db file must be before we consider it
# safe to delete on startup. Two hours covers the worst-case scheduled
# upload window without nuking an in-flight transfer.
TEMP_FILE_MAX_AGE_SECONDS = 2 * 60 * 60

# Directories whose size we report at startup so operators can spot runaway
# growth. We never auto-delete inside these — the contents are business data
# (customer media, per-device DBs, logs already rotated by loguru).
WATCHED_DIRECTORIES = (
    "logs",
    "device_storage",
    "conversation_images",
    "conversation_videos",
    "conversation_voices",
    "avatars",
)

# Substrings used to identify stray child processes during the orphan sweep.
# Matched against the process command line, case-insensitive.
ORPHAN_CMDLINE_NEEDLES = (
    "realtime_reply_process.py",
    "droidrun",
    "scrcpy",
)


# ---------------------------------------------------------------------------
# PID file tracking
# ---------------------------------------------------------------------------


def _ensure_runtime_dir() -> None:
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("runtime_hygiene: cannot create %s: %s", RUNTIME_DIR, exc)


def _pid_file(kind: str, serial: str) -> Path:
    """Return the canonical PID file path for a managed subprocess."""
    safe_serial = serial.replace("/", "_").replace("\\", "_") or "unknown"
    return RUNTIME_DIR / f"{kind}-{safe_serial}.pid"


def register_child_pid(kind: str, serial: str, pid: int) -> None:
    """Record that ``pid`` is a live child of ``kind`` for ``serial``.

    Writes a small text file containing ``<pid>\\n<own_pid>\\n<unix_ts>`` so
    a future startup sweep can decide whether the recorded PID still belongs
    to us (own_pid match) or has been adopted by init (orphan)."""
    _ensure_runtime_dir()
    path = _pid_file(kind, serial)
    try:
        path.write_text(f"{pid}\n{os.getpid()}\n{int(time.time())}\n")
    except OSError as exc:
        logger.warning("runtime_hygiene: cannot write %s: %s", path, exc)


def unregister_child_pid(kind: str, serial: str) -> None:
    """Remove the PID file for a subprocess that exited cleanly."""
    path = _pid_file(kind, serial)
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("runtime_hygiene: cannot delete %s: %s", path, exc)


def list_tracked_pids() -> list[tuple[str, str, int, int, int]]:
    """Return ``(kind, serial, child_pid, parent_pid, ts)`` for every PID file.

    Malformed or empty files are skipped silently; corrupt files are deleted
    so they don't keep tripping the orphan sweep on every restart."""
    if not RUNTIME_DIR.exists():
        return []
    out: list[tuple[str, str, int, int, int]] = []
    for path in RUNTIME_DIR.glob("*.pid"):
        try:
            raw = path.read_text().strip().splitlines()
            child_pid = int(raw[0])
            parent_pid = int(raw[1]) if len(raw) > 1 else 0
            ts = int(raw[2]) if len(raw) > 2 else 0
        except (OSError, ValueError, IndexError):
            try:
                path.unlink()
            except OSError:
                pass
            continue
        # Filename layout: "<kind>-<serial>.pid". Serial may itself contain
        # dashes (some Android serials look like "ABCD-1234"), so we split
        # on the first '-' only.
        stem = path.stem
        if "-" not in stem:
            continue
        kind, _, serial = stem.partition("-")
        out.append((kind, serial, child_pid, parent_pid, ts))
    return out


# ---------------------------------------------------------------------------
# Orphan sweep
# ---------------------------------------------------------------------------


@dataclass
class _OrphanSweepReport:
    killed_from_pidfiles: int = 0
    killed_from_scan: int = 0
    cleaned_pidfiles: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "killed_from_pidfiles": self.killed_from_pidfiles,
            "killed_from_scan": self.killed_from_scan,
            "cleaned_pidfiles": self.cleaned_pidfiles,
            "errors": self.errors[:5],  # cap noise in startup log
        }


def _kill_process_tree(pid: int) -> bool:
    """Best-effort kill of ``pid`` and any children. Returns True on success.

    Tries (in order) psutil's terminate->wait->kill, then os.killpg on Unix,
    then plain os.kill SIGKILL as a last resort."""
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None  # type: ignore

    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            children = proc.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            try:
                proc.terminate()
            except psutil.Error:
                pass
            gone, alive = psutil.wait_procs([proc, *children], timeout=3)
            for survivor in alive:
                try:
                    survivor.kill()
                except psutil.Error:
                    pass
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.Error as exc:
            logger.warning("runtime_hygiene: psutil failed to kill %s: %s", pid, exc)

    if platform.system() != "Windows":
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            time.sleep(1.0)
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return True
        except ProcessLookupError:
            return True
        except OSError as exc:
            logger.warning("runtime_hygiene: killpg failed for %s: %s", pid, exc)
            return False

    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return True
    except (OSError, ProcessLookupError):
        return True


def sweep_orphan_subprocesses() -> _OrphanSweepReport:
    """Kill stray realtime/droidrun/scrcpy subprocesses left over from prior runs.

    Two strategies are combined:

    1. **PID-file driven**: every PID file from a previous backend instance
       belongs to a subprocess whose parent (the previous backend) is gone.
       If the recorded PID is still alive we kill it and remove the file.
    2. **Process-list scan** (psutil only): walk the process list and kill any
       process whose command line matches one of ``ORPHAN_CMDLINE_NEEDLES``
       AND whose parent is PID 1 (i.e. has been adopted by init/launchd) AND
       which is rooted under the project directory.

    This function runs synchronously during startup and never raises."""
    report = _OrphanSweepReport()
    own_pid = os.getpid()
    own_ppid = os.getppid()

    # --- Strategy 1: PID files ---
    for kind, serial, child_pid, parent_pid, ts in list_tracked_pids():
        if parent_pid in (own_pid, own_ppid):
            # Same backend instance (e.g. uvicorn --reload) — leave alone.
            continue
        try:
            os.kill(child_pid, 0)  # alive check
            alive = True
        except (OSError, ProcessLookupError):
            alive = False

        if alive:
            logger.warning(
                "runtime_hygiene: killing orphan %s/%s pid=%d (parent_pid=%d, age=%ds)",
                kind, serial, child_pid, parent_pid, max(0, int(time.time()) - ts),
            )
            if _kill_process_tree(child_pid):
                report.killed_from_pidfiles += 1
            else:
                report.errors.append(f"failed to kill {kind}/{serial} pid={child_pid}")
        # Always remove the stale PID file regardless of whether the process
        # was still around — keeping it would just retrigger the warning.
        try:
            _pid_file(kind, serial).unlink()
            report.cleaned_pidfiles += 1
        except OSError:
            pass

    # --- Strategy 2: process-list scan ---
    try:
        import psutil  # type: ignore
    except ImportError:
        return report

    # Wrap the entire scan loop because some hardened environments (sandbox
    # macOS, restricted containers, missing capabilities on Linux) block the
    # underlying ``sysctl``/``/proc`` reads and psutil raises right at the
    # ``process_iter`` call. We don't want a permission error there to
    # discard the PID-file work we just completed.
    try:
        project_root_str = str(PROJECT_ROOT).lower()
        for proc in psutil.process_iter(["pid", "ppid", "cmdline", "cwd"]):
            try:
                info = proc.info
                cmdline = " ".join(info.get("cmdline") or [])
                if not any(needle in cmdline.lower() for needle in ORPHAN_CMDLINE_NEEDLES):
                    continue
                # Skip our own children — they'll be supervised through the
                # regular path. Only target processes that have been re-parented
                # to init (PID 1 on Unix, often 0 on Windows) or whose parent
                # PID matches a backend that's no longer running.
                if info.get("ppid") == own_pid:
                    continue
                cwd = (info.get("cwd") or "").lower()
                if cwd and project_root_str in cwd or project_root_str in cmdline.lower():
                    logger.warning(
                        "runtime_hygiene: killing reparented subprocess pid=%d cmd=%r",
                        info["pid"], cmdline[:120],
                    )
                    if _kill_process_tree(info["pid"]):
                        report.killed_from_scan += 1
                    else:
                        report.errors.append(f"failed to kill scanned pid={info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
    except (psutil.Error, PermissionError, OSError) as exc:
        # Process-list iteration itself failed (e.g. macOS sandbox blocks
        # sysctl, container without CAP_SYS_PTRACE). Log and degrade — the
        # PID-file strategy above is already finished and reported.
        logger.warning("runtime_hygiene: process-list scan unavailable: %s", exc)
        report.errors.append(f"process_iter failed: {exc}")

    return report


# ---------------------------------------------------------------------------
# Filesystem hygiene
# ---------------------------------------------------------------------------


def _dir_size_bytes(path: Path) -> int:
    """Sum the size of every regular file under ``path`` (best effort)."""
    total = 0
    if not path.exists():
        return 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def cleanup_temp_artifacts() -> dict:
    """Sweep $TMPDIR for stale ``wecom-upload-*.db`` files older than the
    threshold and report sizes for watched directories.

    Returns a small dict suitable for logging in the startup banner."""
    summary: dict = {"deleted_temp_files": 0, "freed_bytes": 0, "watched_dirs": {}}

    tmp_root = Path(tempfile.gettempdir())
    threshold = time.time() - TEMP_FILE_MAX_AGE_SECONDS
    try:
        candidates: Iterable[Path] = list(tmp_root.glob("wecom-upload-*.db"))
    except OSError:
        candidates = []

    for path in candidates:
        try:
            stat = path.stat()
            if stat.st_mtime > threshold:
                continue
            size = stat.st_size
            path.unlink()
            summary["deleted_temp_files"] += 1
            summary["freed_bytes"] += size
        except OSError:
            continue

    for name in WATCHED_DIRECTORIES:
        dir_path = PROJECT_ROOT / name
        size = _dir_size_bytes(dir_path)
        summary["watched_dirs"][name] = size

    return summary


# ---------------------------------------------------------------------------
# ADB baseline
# ---------------------------------------------------------------------------


def _adb_executable() -> str | None:
    """Resolve the adb binary that the backend already configured at startup.

    ``main._configure_adb_path`` exports the chosen path via
    ``ADBUTILS_ADB_PATH`` / ``ADB_PATH``; we honour those first so the
    bundled Windows ``adb.exe`` is preferred over whatever happens to be on
    PATH."""
    return (
        os.environ.get("ADBUTILS_ADB_PATH")
        or os.environ.get("ADB_PATH")
        or shutil.which("adb")
    )


async def reset_adb_baseline(timeout_seconds: float = 8.0) -> dict:
    """Restart the local ADB server so the backend always starts from a
    known-clean daemon.

    Skipped silently when no adb binary is reachable. Returns a small dict
    indicating whether each step succeeded so the caller can log it."""
    adb = _adb_executable()
    summary = {"adb_available": adb is not None, "kill_ok": False, "start_ok": False}
    if not adb:
        return summary

    async def _run(args: list[str]) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                adb, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("runtime_hygiene: adb %s timed out", " ".join(args))
                return False
            if proc.returncode != 0:
                logger.warning(
                    "runtime_hygiene: adb %s exited %s: %s",
                    " ".join(args), proc.returncode, (stderr or b"").decode(errors="replace")[:200],
                )
                return False
            return True
        except (OSError, FileNotFoundError) as exc:
            logger.warning("runtime_hygiene: adb %s failed: %s", " ".join(args), exc)
            return False

    summary["kill_ok"] = await _run(["kill-server"])
    # Even if kill-server "failed" (no server running is treated as failure
    # by some adb builds), we still try to start a fresh one.
    summary["start_ok"] = await _run(["start-server"])
    return summary


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def startup_hygiene() -> dict:
    """Run all startup hygiene steps and return a single summary dict.

    Designed to be called once from the FastAPI ``lifespan`` startup. Never
    raises — every individual step traps its own failures."""
    _ensure_runtime_dir()

    summary: dict = {}
    try:
        summary["orphans"] = sweep_orphan_subprocesses().as_dict()
    except Exception as exc:  # noqa: BLE001
        logger.exception("runtime_hygiene: orphan sweep crashed")
        summary["orphans"] = {"error": str(exc)}

    try:
        summary["fs"] = cleanup_temp_artifacts()
    except Exception as exc:  # noqa: BLE001
        logger.exception("runtime_hygiene: fs cleanup crashed")
        summary["fs"] = {"error": str(exc)}

    try:
        summary["adb"] = await reset_adb_baseline()
    except Exception as exc:  # noqa: BLE001
        logger.exception("runtime_hygiene: adb baseline crashed")
        summary["adb"] = {"error": str(exc)}

    return summary


def shutdown_hygiene() -> None:
    """Clear PID files for any subprocesses that we are about to bring down.

    Called from the FastAPI ``lifespan`` shutdown branch *after* the relevant
    managers have stopped their children. Safe to call multiple times."""
    if not RUNTIME_DIR.exists():
        return
    for path in RUNTIME_DIR.glob("*.pid"):
        try:
            path.unlink()
        except OSError:
            pass
