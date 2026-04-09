"""Tests for video_frame_extract helpers."""

from pathlib import Path

import pytest

from services.video_frame_extract import REVIEW_FRAME_COUNT, frame_sample_times, review_frames_output_dir


def test_frame_sample_times_four_even_buckets():
    times = frame_sample_times(100.0, REVIEW_FRAME_COUNT)
    assert len(times) == 4
    assert times[0] == pytest.approx(12.5, rel=1e-3)
    assert times[1] == pytest.approx(37.5, rel=1e-3)
    assert times[2] == pytest.approx(62.5, rel=1e-3)
    assert times[3] == pytest.approx(87.5, rel=1e-3)


def test_frame_sample_times_short_video_clamped():
    times = frame_sample_times(0.1, REVIEW_FRAME_COUNT)
    assert len(times) == 4
    assert all(0 <= t <= 0.1 for t in times)


def test_frame_sample_times_invalid():
    assert frame_sample_times(0, 4) == []
    assert frame_sample_times(-1, 4) == []


def test_review_frames_output_dir_same_name_folder(tmp_path: Path):
    video = tmp_path / "clips" / "video_4_20260322_202059.mp4"
    video.parent.mkdir(parents=True)
    video.touch()
    out = review_frames_output_dir(video)
    assert out == tmp_path / "clips" / "video_4_20260322_202059"
