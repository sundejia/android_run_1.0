"""
Resolve ffmpeg / ffprobe executables: bundled under wecom-desktop/, then PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from utils.path_utils import get_project_root

__all__ = ["resolve_ffmpeg_binary", "resolve_ffprobe_binary"]


def _wecom_desktop_dir() -> Path:
    return get_project_root() / "wecom-desktop"


def _candidate_names(base: str) -> list[str]:
    if os.name == "nt":
        return [f"{base}.exe", base]
    return [base]


def resolve_ffmpeg_binary() -> Path | None:
    wd = _wecom_desktop_dir()
    candidates: list[Path] = []
    for name in _candidate_names("ffmpeg"):
        candidates.append(wd / name)
    ffmpeg_dir = wd / "ffmpeg"
    if ffmpeg_dir.is_dir():
        for name in _candidate_names("ffmpeg"):
            candidates.append(ffmpeg_dir / name)
    for p in candidates:
        if p.is_file():
            return p
    which = shutil.which("ffmpeg")
    return Path(which) if which else None


def resolve_ffprobe_binary() -> Path | None:
    wd = _wecom_desktop_dir()
    candidates: list[Path] = []
    for name in _candidate_names("ffprobe"):
        candidates.append(wd / name)
    ffprobe_dir = wd / "ffprobe"
    if ffprobe_dir.is_dir():
        for name in _candidate_names("ffprobe"):
            candidates.append(ffprobe_dir / name)
    ffmpeg_bin = resolve_ffmpeg_binary()
    if ffmpeg_bin and ffmpeg_bin.parent.is_dir():
        for name in _candidate_names("ffprobe"):
            candidates.append(ffmpeg_bin.parent / name)
    for p in candidates:
        if p.is_file():
            return p
    which = shutil.which("ffprobe")
    return Path(which) if which else None
