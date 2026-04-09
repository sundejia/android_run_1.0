"""Whitelist rules for serving video review frame JPEGs."""

from routers.resources import _review_frame_path_allowed


def test_review_frame_path_allowed_legacy_layout():
    assert _review_frame_path_allowed(
        "conversation_videos/review_frames/msg_1/frame_0.jpg",
        None,
    )


def test_review_frame_path_allowed_next_to_video_same_name_dir():
    assert _review_frame_path_allowed(
        "conversation_videos/foo/bar/frame_0.jpg",
        "conversation_videos/foo/bar.mp4",
    )


def test_review_frame_path_allowed_rejects_parent_escape():
    assert not _review_frame_path_allowed(
        "conversation_videos/foo/../../../secrets.jpg",
        "conversation_videos/foo/bar.mp4",
    )


def test_review_frame_path_allowed_rejects_wrong_subfolder():
    assert not _review_frame_path_allowed(
        "conversation_videos/foo/other_stem/frame_0.jpg",
        "conversation_videos/foo/bar.mp4",
    )
