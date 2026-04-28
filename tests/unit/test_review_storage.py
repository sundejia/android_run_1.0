"""Tests for the review-side SQLite tables (pending_reviews, review_verdicts,
webhook_idempotency, analytics_events) and their access helpers.

Each test gets a fresh DB initialised via ``init_database`` so we exercise
the real schema rather than re-declaring it inline.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from wecom_automation.database.schema import init_database
from wecom_automation.services.review.storage import (
    ReviewStorage,
    ReviewVerdictRow,
    PendingReviewRow,
)


@pytest.fixture()
def fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "android.db"
    os.environ["WECOM_DB_PATH"] = str(db)
    init_database(str(db), force_recreate=True)
    return db


@pytest.fixture()
def storage(fresh_db: Path) -> ReviewStorage:
    return ReviewStorage(str(fresh_db))


class TestPendingReviews:
    def test_insert_and_get(self, storage: ReviewStorage) -> None:
        row = PendingReviewRow(
            message_id=42,
            customer_id=1,
            customer_name="张三",
            device_serial="dev-1",
            channel="@WeChat",
            kefu_name="客服A",
            image_path="/tmp/x.png",
        )
        storage.insert_pending_review(row)

        fetched = storage.get_pending_review(42)
        assert fetched is not None
        assert fetched.message_id == 42
        assert fetched.status == "pending"
        assert fetched.attempts == 0

    def test_idempotent_insert_does_not_duplicate(self, storage: ReviewStorage) -> None:
        row = PendingReviewRow(
            message_id=42,
            customer_id=1,
            customer_name="x",
            device_serial="d",
            channel=None,
            kefu_name="k",
            image_path="/tmp/x.png",
        )
        storage.insert_pending_review(row)
        # Second insert with same key: should NOT raise; should NOT create duplicate
        storage.insert_pending_review(row)
        rows = storage.list_pending_reviews(status="pending")
        assert len([r for r in rows if r.message_id == 42]) == 1

    def test_mark_status(self, storage: ReviewStorage) -> None:
        storage.insert_pending_review(
            PendingReviewRow(
                message_id=42,
                customer_id=1,
                customer_name="x",
                device_serial="d",
                channel=None,
                kefu_name="k",
                image_path="/tmp/x.png",
            )
        )
        storage.mark_pending_status(42, "approved")
        fetched = storage.get_pending_review(42)
        assert fetched is not None
        assert fetched.status == "approved"

    def test_increment_attempts(self, storage: ReviewStorage) -> None:
        storage.insert_pending_review(
            PendingReviewRow(
                message_id=42,
                customer_id=1,
                customer_name="x",
                device_serial="d",
                channel=None,
                kefu_name="k",
                image_path="/tmp/x.png",
            )
        )
        storage.increment_attempts(42, last_error="boom")
        storage.increment_attempts(42, last_error="boom2")
        fetched = storage.get_pending_review(42)
        assert fetched is not None
        assert fetched.attempts == 2
        assert fetched.last_error == "boom2"

    def test_list_filters_by_status(self, storage: ReviewStorage) -> None:
        for mid, status in ((1, "pending"), (2, "approved"), (3, "rejected")):
            row = PendingReviewRow(
                message_id=mid,
                customer_id=1,
                customer_name="x",
                device_serial="d",
                channel=None,
                kefu_name="k",
                image_path="/tmp/x.png",
            )
            storage.insert_pending_review(row)
            if status != "pending":
                storage.mark_pending_status(mid, status)
        pending = storage.list_pending_reviews(status="pending")
        assert {r.message_id for r in pending} == {1}


class TestVerdicts:
    def test_upsert_and_get(self, storage: ReviewStorage) -> None:
        v = ReviewVerdictRow(
            message_id=42,
            image_id="img-1",
            decision="合格",
            is_portrait=True,
            is_real_person=True,
            face_visible=True,
            final_score=7.5,
            raw_payload_json='{"ok":true}',
            prompt_version_id="pv-2",
            skill_version="v1",
            received_at="2026-04-28T12:00:00+00:00",
        )
        storage.upsert_verdict(v)
        fetched = storage.get_verdict(42)
        assert fetched is not None
        assert fetched.decision == "合格"
        assert fetched.is_portrait is True
        assert fetched.face_visible is True
        assert fetched.final_score == 7.5

    def test_upsert_overwrites(self, storage: ReviewStorage) -> None:
        for decision in ("不合格", "合格"):
            storage.upsert_verdict(
                ReviewVerdictRow(
                    message_id=42,
                    image_id="img",
                    decision=decision,
                    is_portrait=True,
                    is_real_person=True,
                    face_visible=True,
                    final_score=1.0,
                    raw_payload_json="{}",
                    prompt_version_id="pv",
                    skill_version="v1",
                    received_at="2026-04-28T12:00:00+00:00",
                )
            )
        fetched = storage.get_verdict(42)
        assert fetched is not None
        assert fetched.decision == "合格"


class TestIdempotency:
    def test_first_seen_returns_true_then_false(self, storage: ReviewStorage) -> None:
        assert storage.try_register_idempotency_key("k1", "2026-04-28T12:00:00+00:00") is True
        assert storage.try_register_idempotency_key("k1", "2026-04-28T12:00:00+00:00") is False

    def test_purge_old_keys(self, storage: ReviewStorage) -> None:
        storage.try_register_idempotency_key("old", "2020-01-01T00:00:00+00:00")
        storage.try_register_idempotency_key("new", "2026-04-28T12:00:00+00:00")
        purged = storage.purge_old_idempotency("2026-04-27T00:00:00+00:00")
        assert purged == 1
        assert storage.try_register_idempotency_key("new", "x") is False
        assert storage.try_register_idempotency_key("old", "x") is True


class TestAnalytics:
    def test_record_and_list(self, storage: ReviewStorage) -> None:
        storage.record_event("review_submitted", trace_id="42", payload={"ok": True})
        storage.record_event("review_approved", trace_id="42", payload={"x": 1})
        events = storage.list_events()
        assert len(events) == 2
        # newest first
        assert events[0].event_type == "review_approved"
        assert events[0].trace_id == "42"

    def test_filter_by_type(self, storage: ReviewStorage) -> None:
        storage.record_event("a", trace_id="t", payload={})
        storage.record_event("b", trace_id="t", payload={})
        events = storage.list_events(event_type="b")
        assert len(events) == 1
        assert events[0].event_type == "b"
