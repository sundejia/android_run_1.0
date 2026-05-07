"""TDD tests for boss_automation/services/template_engine.py."""

from __future__ import annotations

import pytest

from boss_automation.services.template_engine import (
    RenderResult,
    render_template,
)


def test_substitutes_simple_placeholders() -> None:
    out = render_template(
        "你好 {name}，{position} 这个岗位还在招吗？",
        {"name": "李雷", "position": "Java"},
    )
    assert isinstance(out, RenderResult)
    assert out.text == "你好 李雷，Java 这个岗位还在招吗？"
    assert out.warnings == ()


def test_unknown_placeholder_left_as_is_and_warns() -> None:
    out = render_template("Hi {name}, {missing}", {"name": "Lei"})
    assert "{missing}" in out.text
    assert out.warnings == ("missing",)


def test_conditional_segment_emitted_when_value_truthy() -> None:
    out = render_template(
        "你好 {name}{?expected_salary:，期望 {expected_salary} 我们能匹配}",
        {"name": "李雷", "expected_salary": "40K-60K"},
    )
    assert out.text == "你好 李雷，期望 40K-60K 我们能匹配"


def test_conditional_segment_omitted_when_value_missing_or_empty() -> None:
    out = render_template(
        "你好 {name}{?expected_salary:，期望 {expected_salary} 我们能匹配}",
        {"name": "李雷", "expected_salary": ""},
    )
    assert out.text == "你好 李雷"

    out2 = render_template(
        "你好 {name}{?expected_salary:，期望 {expected_salary} 我们能匹配}",
        {"name": "李雷"},
    )
    assert out2.text == "你好 李雷"


def test_truncates_to_limit_with_ellipsis() -> None:
    body = "x" * 600
    out = render_template(body, {}, max_length=480)
    assert len(out.text) == 480
    assert out.text.endswith("…")


def test_does_not_truncate_when_within_limit() -> None:
    body = "x" * 100
    out = render_template(body, {}, max_length=480)
    assert out.text == body


def test_empty_template_returns_empty_string() -> None:
    out = render_template("", {"name": "x"})
    assert out.text == ""


def test_none_values_are_treated_as_missing() -> None:
    out = render_template("你好 {name}{?company:，{company}}", {"name": "李雷", "company": None})
    assert out.text == "你好 李雷"


def test_render_result_is_immutable() -> None:
    from dataclasses import FrozenInstanceError

    out = render_template("x", {})
    with pytest.raises((AttributeError, FrozenInstanceError)):
        out.text = "y"  # type: ignore[misc]
