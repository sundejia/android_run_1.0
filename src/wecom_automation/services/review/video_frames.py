"""Extract a representative video frame for review-gated media actions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _resolve_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def review_frame_path(video_path: Path) -> Path:
    """Return the deterministic JPEG path used for a video's gate review frame."""
    return video_path.expanduser().resolve().with_suffix(".review.jpg")


def extract_review_frame(video_path: str | Path) -> Path:
    """Extract one representative JPEG frame from a local video file.

    The frame is used only as input to the existing image review service. If
    ffmpeg is unavailable or extraction fails, an exception is raised so callers
    can fail closed and skip automation.
    """
    src = Path(video_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Video file not found: {src}")

    out = review_frame_path(src)
    ffmpeg = _resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "00:00:00.5",
        "-i",
        str(src),
        "-vframes",
        "1",
        "-vf",
        "scale=720:-1",
        "-q:v",
        "2",
        "-y",
        str(out),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg timed out extracting review frame") from exc
    except OSError as exc:
        raise RuntimeError(f"ffmpeg failed to run: {exc}") from exc

    if result.returncode != 0 or not out.is_file():
        err = (result.stderr or b"").decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"ffmpeg failed extracting review frame: {err or result.returncode}")
    return out
