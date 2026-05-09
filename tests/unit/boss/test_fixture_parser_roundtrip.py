"""CI guard — every real-device fixture must parse successfully.

Rationale
---------
The 2026-05-08 E2E test report found that every BOSS parser was
silently broken against the live app because the unit tests only
exercised synthetic (hand-written) fixtures. Synthetic fixtures lag
real-app UI changes, so coverage was green while production was 100%
broken.

This module fills that gap with a "fixture round-trip" smoke: any
JSON fixture captured by ``scripts/dump_boss_ui.py`` and named with
the ``e2e_`` prefix must be parseable by the parser that owns its
page. The next operator to dump a new real-device snapshot
automatically gets CI coverage that the parsers still work — no
code change required.

If you add a new page to the capture workflow, register its dispatch
in ``_PAGE_PARSERS`` so CI covers it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "boss"


def _assert_recruiter_profile(tree: dict[str, Any]) -> None:
    from boss_automation.parsers.recruiter_profile_parser import (
        LoginState,
        detect_login_state,
        extract_recruiter_profile,
    )

    state = detect_login_state(tree)
    assert state == LoginState.LOGGED_IN, (
        f"me_profile fixture must be classified LOGGED_IN, got {state.value!r} — "
        "update the parser to handle the new BOSS app UI schema."
    )
    profile = extract_recruiter_profile(tree)
    assert profile is not None, (
        "me_profile fixture must yield a RecruiterProfile — parser returned "
        "None, which means the resource-id or contentDescription it targets "
        "is no longer present in the real app. Update _NAME_IDS / "
        "_COMPANY_AND_POSITION_IDS / _NAME_CONTENT_DESC_IDS to match the "
        "captured fixture."
    )
    assert profile.name, "extracted profile has empty name"


def _assert_job_list(tree: dict[str, Any]) -> None:
    from boss_automation.parsers.job_list_parser import parse_job_list

    jobs = parse_job_list(tree)
    assert jobs, (
        "jobs_list fixture must parse at least one job — parser returned "
        "empty. Check that the card-level resource-ids still match."
    )


def _assert_message_list(tree: dict[str, Any]) -> None:
    from boss_automation.parsers.message_list_parser import parse_message_list

    conversations = parse_message_list(tree)
    assert conversations, "messages_list fixture must parse at least one conversation row."


def _assert_candidate_card(tree: dict[str, Any]) -> None:
    from boss_automation.parsers.candidate_card_parser import parse_candidate_feed

    cards = parse_candidate_feed(tree)
    assert cards, "candidates_feed fixture must parse at least one candidate card."


_PAGE_PARSERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "me_profile": _assert_recruiter_profile,
    "jobs_list": _assert_job_list,
    "messages_list": _assert_message_list,
    "candidates_feed": _assert_candidate_card,
}


def _discover_e2e_fixtures() -> list[tuple[str, Path]]:
    """Find every ``tests/fixtures/boss/<page>/e2e_*.json`` file."""
    if not FIXTURE_ROOT.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for page_dir in sorted(FIXTURE_ROOT.iterdir()):
        if not page_dir.is_dir():
            continue
        page = page_dir.name
        if page not in _PAGE_PARSERS:
            continue
        for fixture_path in sorted(page_dir.glob("e2e_*.json")):
            out.append((page, fixture_path))
    return out


_FIXTURES = _discover_e2e_fixtures()


@pytest.mark.skipif(
    not _FIXTURES,
    reason=(
        "no e2e_*.json fixtures captured yet; run "
        "`scripts/dump_boss_ui.py --label e2e_<date>` on a real device "
        "to populate the roundtrip guard."
    ),
)
@pytest.mark.parametrize(
    ("page", "fixture_path"),
    _FIXTURES,
    ids=[str(p.relative_to(FIXTURE_ROOT)) for _, p in _FIXTURES],
)
def test_real_device_fixture_round_trips_through_parser(page: str, fixture_path: Path) -> None:
    fixture = load_fixture(fixture_path)
    assert fixture.page == page, f"fixture file lives under {page}/ but declares page={fixture.page!r}"
    _PAGE_PARSERS[page](fixture.ui_tree)
