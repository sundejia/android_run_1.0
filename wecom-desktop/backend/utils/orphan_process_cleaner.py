"""
Orphan realtime-reply subprocess cleaner.

Why this exists
---------------
`RealtimeReplyManager` spawns per-device subprocess trees via
``subprocess.Popen(..., shell=True, creationflags=CREATE_NEW_PROCESS_GROUP)``.
Those trees look like ``cmd.exe -> uv.exe -> python.exe -> python.exe``
and each leaf runs ``realtime_reply_process.py --serial <serial>``.

When uvicorn is launched with ``--reload`` (the project's standard dev mode),
any file change causes uvicorn to terminate the worker Python process. Because
the realtime-reply subprocess trees use ``CREATE_NEW_PROCESS_GROUP`` and are
launched through a separate ``cmd.exe``, they survive the reload and become
orphans:

- Their parent ``cmd.exe`` has a dead grandparent.
- The new backend worker loads a fresh ``RealtimeReplyManager`` singleton
  whose ``self._processes`` dict is empty, so the "already running" guard
  in ``start_realtime_reply`` does not fire.
- When the user (or auto-restart) triggers another start for the same
  serial, the new subprocess tree and the old orphan tree both drive the
  same Android device through ADB/DroidRun, causing swipe failures
  (``[Errno 22] Invalid argument``), flapping scan counters, and the
  "left side refreshes, then right side refreshes" alternating-freeze
  symptom.

This module provides two layers of defence:

- :func:`kill_realtime_reply_orphans` takes an optional ``serial`` and
  kills the matching subprocess tree(s). Call this right before spawning
  a new realtime-reply subprocess (Layer 1).
- The same function with ``serial=None`` is safe to call at backend
  startup to wipe every orphan left behind by a prior reload (Layer 2).

Both layers are best-effort: failures are logged, never raised, so they
cannot block the primary startup / start flow.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - psutil is pinned in the venv
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Script filename we look for in the command line. Deliberately kept as a
# plain filename so the match works regardless of path separators, drive
# letters, or whether the path is quoted.
_REALTIME_REPLY_SCRIPT = "realtime_reply_process.py"


def _matches_realtime(cmdline: str, serial: str | None) -> bool:
    """Return True if *cmdline* belongs to a realtime-reply subprocess."""
    if _REALTIME_REPLY_SCRIPT not in cmdline:
        return False
    if serial is None:
        return True
    # Accept both ``--serial ABC`` and ``--serial "ABC"`` forms.
    return (f"--serial {serial}" in cmdline) or (f'--serial "{serial}"' in cmdline)


def _iter_matching_processes(
    predicate: Callable[[str], bool],
) -> list[psutil.Process]:
    """Yield processes whose joined command line matches *predicate*."""
    if psutil is None:
        return []

    matches: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline_parts = proc.info.get("cmdline") or []
            cmdline = " ".join(cmdline_parts)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not cmdline:
            continue
        if predicate(cmdline):
            matches.append(proc)
    return matches


def _select_tree_roots(procs: list[psutil.Process]) -> list[psutil.Process]:
    """Return only the top-most matching process in each tree.

    A single realtime-reply subprocess tree has four matching processes
    (cmd/uv/python/python). We only want to fire one ``terminate`` per
    tree: killing the outermost ancestor cleans up the rest via
    ``children(recursive=True)``.
    """
    if not procs:
        return []

    own_pid = os.getpid()
    pid_set = {p.pid for p in procs}
    roots: list[psutil.Process] = []
    for proc in procs:
        try:
            if proc.pid == own_pid:
                continue
            ancestors = proc.parents()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if any(a.pid in pid_set for a in ancestors):
            continue
        roots.append(proc)
    return roots


def _kill_tree(proc: psutil.Process, timeout: float = 5.0) -> int:
    """Terminate *proc* and all its descendants. Returns the count killed."""
    try:
        descendants = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = []

    targets = descendants + [proc]
    for t in targets:
        try:
            t.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _, alive = psutil.wait_procs(targets, timeout=timeout)
    for t in alive:
        try:
            t.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    psutil.wait_procs(alive, timeout=timeout)
    return len(targets)


def kill_realtime_reply_orphans(serial: str | None = None) -> dict:
    """Kill orphan realtime-reply subprocess trees.

    Args:
        serial: If given, only kill trees whose command line targets this
            device serial. If ``None``, kill every realtime-reply tree
            found on the host.

    Returns:
        A dict with keys ``trees_killed`` (root subprocess trees that were
        terminated) and ``processes_killed`` (approximate count of
        processes inside those trees). An empty/zeroed dict means there
        was nothing to clean up.
    """
    result = {"trees_killed": 0, "processes_killed": 0}

    if psutil is None:
        logger.warning("psutil is not available; cannot scan for orphan realtime-reply processes")
        return result

    try:
        matches = _iter_matching_processes(lambda cmd: _matches_realtime(cmd, serial))
    except Exception as e:  # pragma: no cover - psutil shouldn't raise here
        logger.warning("Orphan scan failed: %s", e)
        return result

    if not matches:
        return result

    roots = _select_tree_roots(matches)
    if not roots:
        return result

    for root in roots:
        try:
            pid = root.pid
            cmdline = " ".join(root.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        try:
            n = _kill_tree(root)
        except Exception as e:
            logger.warning("Failed to terminate orphan tree pid=%s: %s", pid, e)
            continue

        result["trees_killed"] += 1
        result["processes_killed"] += n
        logger.warning(
            "Killed orphan realtime-reply tree pid=%s (%d procs) cmd=%s",
            pid,
            n,
            cmdline,
        )

    return result
