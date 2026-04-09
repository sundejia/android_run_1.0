"""
Extract evenly spaced JPEG frames from a video file for AI review (4 frames).
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from utils.ffmpeg_bins import resolve_ffmpeg_binary, resolve_ffprobe_binary
from utils.path_utils import get_project_root

REVIEW_FRAME_COUNT = 4
EPS = 0.05


@dataclass(frozen=True)
class ExtractedFrame:
    """One extracted frame on disk (path relative to project root)."""

    frame_index: int
    percent: float
    time_seconds: float
    relative_path: str


def frame_sample_times(duration_seconds: float, count: int = REVIEW_FRAME_COUNT) -> list[float]:
    """Return `count` timestamps in (0, T), evenly spaced: (k+0.5)/count * T."""
    if duration_seconds <= 0 or not math.isfinite(duration_seconds):
        return []
    t = float(duration_seconds)
    times: list[float] = []
    for k in range(count):
        sec = (k + 0.5) / count * t
        sec = min(max(0.0, sec), max(0.0, t - EPS))
        times.append(sec)
    return times


def review_frames_output_dir(video_path: Path) -> Path:
    """Directory for AI review JPEGs: same folder as the video, subdir named like the file stem."""
    p = video_path.expanduser().resolve()
    return p.parent / p.stem


def probe_duration_seconds(video_path: Path) -> float | None:
    """Return container duration in seconds using ffprobe, or None."""
    ffprobe = resolve_ffprobe_binary()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        line = (result.stdout or "").strip().splitlines()
        if not line:
            return None
        return float(line[0])
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return None


def extract_review_frames(
    video_path: Path,
    message_id: int,
    *,
    duration_seconds: float | None = None,
) -> tuple[list[ExtractedFrame], str | None]:
    """
    Write REVIEW_FRAME_COUNT JPEGs next to the video: ``<video_dir>/<video_stem>/frame_{i}.jpg``.

    ``message_id`` is kept for API compatibility; output layout follows the video file path only.

    Returns:
        (frames, error_message). On failure, frames is empty and error_message is set.
    """
    video_path = video_path.expanduser().resolve()
    if not video_path.is_file():
        return [], f"Video file not found: {video_path}"

    ffmpeg = resolve_ffmpeg_binary()
    if not ffmpeg:
        return [], "ffmpeg not found (install or place under wecom-desktop/ffmpeg)"

    dur = duration_seconds
    if dur is None or dur <= 0:
        probed = probe_duration_seconds(video_path)
        dur = probed if probed is not None else None
    if dur is None or dur <= 0:
        return [], "Could not determine video duration (ffprobe missing or failed)"

    _ = message_id  # API compatibility; frame paths follow video location only.

    project_root = get_project_root().resolve()
    out_dir = review_frames_output_dir(video_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    times = frame_sample_times(dur, REVIEW_FRAME_COUNT)
    if len(times) != REVIEW_FRAME_COUNT:
        return [], "Invalid duration for frame sampling"

    frames: list[ExtractedFrame] = []
    for idx, sec in enumerate(times):
        out_file = out_dir / f"frame_{idx}.jpg"
        hh = int(sec // 3600)
        mm = int((sec % 3600) // 60)
        ss = sec % 60
        tstamp = f"{hh:02d}:{mm:02d}:{ss:06.3f}"
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            tstamp,
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-vf",
            "scale=720:-1",
            "-q:v",
            "2",
            "-y",
            str(out_file),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return [], f"ffmpeg timed out extracting frame {idx}"
        except OSError as exc:
            return [], f"ffmpeg failed to run: {exc}"

        if result.returncode != 0 or not out_file.is_file():
            err = (result.stderr or b"").decode("utf-8", errors="replace")[:500]
            return [], f"ffmpeg failed for frame {idx}: {err or result.returncode}"

        try:
            rel = str(out_file.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            rel = str(out_file)
        percent = (idx + 0.5) / REVIEW_FRAME_COUNT
        frames.append(
            ExtractedFrame(
                frame_index=idx,
                percent=percent,
                time_seconds=sec,
                relative_path=rel,
            )
        )

    return frames, None
