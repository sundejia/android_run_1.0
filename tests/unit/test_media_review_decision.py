"""
Tests for media_review_decision.evaluate_gate_pass.

Covers the shared portrait/decision gate used by AutoGroupInviteAction
and AutoBlacklistAction. Exercises image vs. video paths, gate-enabled
vs. disabled, the video majority rule, and missing/malformed data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.media_actions.media_review_decision import (
    MediaReviewDecision,
    evaluate_gate_pass,
)

# ---------------------------------------------------------------------------
# Helpers: build a real SQLite DB with images / videos + messages rows.
# ---------------------------------------------------------------------------


def _init_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "conv.db")
    # ConversationRepository(auto_init=True) creates schema via run_migrations
    # but we already get the latest schema via init_database. Just instantiate.
    ConversationRepository(db_path, auto_init=True)
    return db_path


def _seed_message(
    db_path: str,
    *,
    message_id: int,
    customer_id: int = 1,
    message_type: str = "image",
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO kefus (id, name) VALUES (1, 'k')")
        cur.execute(
            "INSERT OR IGNORE INTO customers (id, name, kefu_id) VALUES (?, 'c', 1)",
            (customer_id,),
        )
        cur.execute(
            """
            INSERT INTO messages (id, customer_id, content, message_type, message_hash, is_from_kefu)
            VALUES (?, ?, '', ?, ?, 0)
            """,
            (message_id, customer_id, message_type, f"hash-{message_id}"),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_image_row(
    db_path: str,
    *,
    message_id: int,
    ai_review_status: str | None,
    ai_review_decision: str | None,
    details: dict | None,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO images (
                message_id, file_path, ai_review_status, ai_review_decision,
                ai_review_details_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                message_id,
                f"img/{message_id}.jpg",
                ai_review_status,
                ai_review_decision,
                json.dumps(details, ensure_ascii=False) if details is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_video_row(
    db_path: str,
    *,
    message_id: int,
    ai_review_status: str | None,
    frames: list[dict] | None,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO videos (
                message_id, file_path, ai_review_status, ai_review_frames_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                message_id,
                f"vid/{message_id}.mp4",
                ai_review_status,
                json.dumps(frames, ensure_ascii=False) if frames is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _frame(*, is_portrait: bool, decision: str) -> dict:
    """Build a per-frame entry matching the runtime shape."""
    return {
        "frame_index": 0,
        "ai_review_details_json": json.dumps(
            {"result": {"is_portrait": is_portrait, "decision": decision}},
            ensure_ascii=False,
        ),
    }


# ---------------------------------------------------------------------------
# Image scenarios
# ---------------------------------------------------------------------------


class TestImageGate:
    def test_gate_off_portrait_true_passes(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=10)
        _insert_image_row(
            db_path,
            message_id=10,
            ai_review_status="completed",
            ai_review_decision="不合格",
            details={"result": {"is_portrait": True, "decision": "不合格"}},
        )

        result = evaluate_gate_pass(
            message_id=10,
            message_type="image",
            db_path=db_path,
            gate_enabled=False,
        )

        assert isinstance(result, MediaReviewDecision)
        assert result.gate_pass is True
        assert result.has_data is True

    def test_gate_off_portrait_false_skips(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=11)
        _insert_image_row(
            db_path,
            message_id=11,
            ai_review_status="completed",
            ai_review_decision="合格",
            details={"result": {"is_portrait": False, "decision": "合格"}},
        )

        result = evaluate_gate_pass(
            message_id=11,
            message_type="image",
            db_path=db_path,
            gate_enabled=False,
        )

        assert result.gate_pass is False
        assert result.has_data is True
        assert result.reason == "portrait_false"

    def test_gate_on_portrait_and_qualified_passes(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=12)
        _insert_image_row(
            db_path,
            message_id=12,
            ai_review_status="completed",
            ai_review_decision="合格",
            details={"result": {"is_portrait": True, "decision": "合格"}},
        )

        result = evaluate_gate_pass(
            message_id=12,
            message_type="image",
            db_path=db_path,
            gate_enabled=True,
        )

        assert result.gate_pass is True
        assert result.has_data is True

    def test_gate_on_portrait_true_unqualified_skips(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=13)
        _insert_image_row(
            db_path,
            message_id=13,
            ai_review_status="completed",
            ai_review_decision="不合格",
            details={"result": {"is_portrait": True, "decision": "不合格"}},
        )

        result = evaluate_gate_pass(
            message_id=13,
            message_type="image",
            db_path=db_path,
            gate_enabled=True,
        )

        assert result.gate_pass is False
        assert result.has_data is True
        assert result.reason == "decision_not_qualified"

    def test_pending_status_reports_no_data(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=14)
        _insert_image_row(
            db_path,
            message_id=14,
            ai_review_status="pending",
            ai_review_decision=None,
            details=None,
        )

        result = evaluate_gate_pass(
            message_id=14,
            message_type="image",
            db_path=db_path,
            gate_enabled=True,
        )

        assert result.gate_pass is False
        assert result.has_data is False

    def test_image_row_missing(self, tmp_path):
        db_path = _init_db(tmp_path)
        # No row inserted at all.
        result = evaluate_gate_pass(
            message_id=999,
            message_type="image",
            db_path=db_path,
            gate_enabled=True,
        )
        assert result.gate_pass is False
        assert result.has_data is False
        assert result.reason == "image_row_missing"

    def test_unparsable_details_json(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=15)
        # Manual insert with a malformed JSON string.
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO images (message_id, file_path, ai_review_status, ai_review_details_json) VALUES (?, ?, ?, ?)",
            (15, "x.jpg", "completed", "{not_valid_json"),
        )
        conn.commit()
        conn.close()

        result = evaluate_gate_pass(
            message_id=15,
            message_type="image",
            db_path=db_path,
            gate_enabled=True,
        )
        assert result.has_data is False
        assert result.reason == "details_json_unparsable"


# ---------------------------------------------------------------------------
# Video scenarios — majority-of-frames rule
# ---------------------------------------------------------------------------


class TestVideoGate:
    def test_two_of_four_portrait_passes_gate_off(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=20, message_type="video")
        frames = [
            _frame(is_portrait=True, decision="合格"),
            _frame(is_portrait=True, decision="合格"),
            _frame(is_portrait=False, decision="不合格"),
            _frame(is_portrait=False, decision="不合格"),
        ]
        _insert_video_row(db_path, message_id=20, ai_review_status="completed", frames=frames)

        result = evaluate_gate_pass(
            message_id=20,
            message_type="video",
            db_path=db_path,
            gate_enabled=False,
        )

        assert result.gate_pass is True
        assert result.has_data is True
        assert result.details["passed_frames"] == 2
        assert result.details["total_frames"] == 4

    def test_one_of_four_portrait_skips(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=21, message_type="video")
        frames = [
            _frame(is_portrait=True, decision="合格"),
            _frame(is_portrait=False, decision="不合格"),
            _frame(is_portrait=False, decision="不合格"),
            _frame(is_portrait=False, decision="不合格"),
        ]
        _insert_video_row(db_path, message_id=21, ai_review_status="completed", frames=frames)

        result = evaluate_gate_pass(
            message_id=21,
            message_type="video",
            db_path=db_path,
            gate_enabled=False,
        )

        assert result.gate_pass is False
        assert result.has_data is True
        assert result.reason == "video_passed_below_threshold"

    def test_gate_on_three_portrait_two_qualified_skips(self, tmp_path):
        """When gate_enabled, we count portrait+合格 frames; here only 2/4 -> threshold==2 passes."""
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=22, message_type="video")
        frames = [
            _frame(is_portrait=True, decision="合格"),
            _frame(is_portrait=True, decision="合格"),
            _frame(is_portrait=True, decision="不合格"),
            _frame(is_portrait=False, decision="合格"),
        ]
        _insert_video_row(db_path, message_id=22, ai_review_status="completed", frames=frames)

        result = evaluate_gate_pass(
            message_id=22,
            message_type="video",
            db_path=db_path,
            gate_enabled=True,
        )

        # 2/4 passes >= ceil(4*0.5)=2, so gate passes.
        assert result.gate_pass is True
        assert result.details["passed_frames"] == 2

    def test_gate_on_only_one_qualified_skips(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=23, message_type="video")
        frames = [
            _frame(is_portrait=True, decision="合格"),
            _frame(is_portrait=True, decision="不合格"),
            _frame(is_portrait=True, decision="不合格"),
            _frame(is_portrait=False, decision="合格"),
        ]
        _insert_video_row(db_path, message_id=23, ai_review_status="completed", frames=frames)

        result = evaluate_gate_pass(
            message_id=23,
            message_type="video",
            db_path=db_path,
            gate_enabled=True,
        )

        # Only 1/4 passes -> below ceil(4*0.5)=2.
        assert result.gate_pass is False
        assert result.has_data is True
        assert result.details["passed_frames"] == 1

    def test_partial_status_with_one_pass_three_failures_returns_data(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=24, message_type="video")
        frames = [
            _frame(is_portrait=True, decision="合格"),
            {"frame_index": 1, "ai_review_details_json": None},
            {"frame_index": 2, "ai_review_details_json": None},
            {"frame_index": 3, "ai_review_details_json": None},
        ]
        _insert_video_row(db_path, message_id=24, ai_review_status="partial", frames=frames)

        result = evaluate_gate_pass(
            message_id=24,
            message_type="video",
            db_path=db_path,
            gate_enabled=False,
        )

        # 1 pass / 4 total -> below threshold but data is present.
        assert result.has_data is True
        assert result.gate_pass is False

    def test_failed_status_reports_no_data(self, tmp_path):
        db_path = _init_db(tmp_path)
        _seed_message(db_path, message_id=25, message_type="video")
        _insert_video_row(db_path, message_id=25, ai_review_status="failed", frames=None)

        result = evaluate_gate_pass(
            message_id=25,
            message_type="video",
            db_path=db_path,
            gate_enabled=False,
        )

        assert result.gate_pass is False
        assert result.has_data is False

    def test_video_row_missing(self, tmp_path):
        db_path = _init_db(tmp_path)

        result = evaluate_gate_pass(
            message_id=8888,
            message_type="video",
            db_path=db_path,
            gate_enabled=False,
        )

        assert result.gate_pass is False
        assert result.has_data is False
        assert result.reason == "video_row_missing"


# ---------------------------------------------------------------------------
# Caller-arg edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_db_path_none_returns_no_data(self):
        result = evaluate_gate_pass(
            message_id=1,
            message_type="image",
            db_path=None,
            gate_enabled=False,
        )
        assert result.gate_pass is False
        assert result.has_data is False
        assert result.reason == "db_path_not_configured"

    def test_message_id_none_returns_no_data(self, tmp_path):
        db_path = _init_db(tmp_path)
        result = evaluate_gate_pass(
            message_id=None,
            message_type="image",
            db_path=db_path,
            gate_enabled=False,
        )
        assert result.has_data is False
        assert result.reason == "message_id_missing"

    def test_unsupported_message_type_returns_no_data(self, tmp_path):
        db_path = _init_db(tmp_path)
        result = evaluate_gate_pass(
            message_id=1,
            message_type="text",
            db_path=db_path,
            gate_enabled=False,
        )
        assert result.has_data is False
        assert "unsupported_message_type" in result.reason
