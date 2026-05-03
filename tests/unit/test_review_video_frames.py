from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wecom_automation.services.review import video_frames


def test_review_frame_path_is_deterministic(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"

    assert video_frames.review_frame_path(video) == (tmp_path / "clip.review.jpg").resolve()


def test_extract_review_frame_raises_when_ffmpeg_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(video_frames, "_resolve_ffmpeg", lambda: None)

    with pytest.raises(RuntimeError, match="ffmpeg not found"):
        video_frames.extract_review_frame(video)


def test_extract_review_frame_writes_expected_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(video_frames, "_resolve_ffmpeg", lambda: "ffmpeg")

    def fake_run(cmd, capture_output, timeout):
        Path(cmd[-1]).write_bytes(b"jpg")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(video_frames.subprocess, "run", fake_run)

    out = video_frames.extract_review_frame(video)

    assert out == tmp_path / "clip.review.jpg"
    assert out.read_bytes() == b"jpg"
