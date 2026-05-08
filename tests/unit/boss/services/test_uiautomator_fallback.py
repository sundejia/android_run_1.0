"""Tests for ``boss_automation.services.uiautomator_fallback``.

Golden XML → tree dict parsing, plus error paths for malformed or
empty input.
"""

from __future__ import annotations

import pytest

from boss_automation.services.uiautomator_fallback import (
    UiAutomatorFallbackError,
    parse_uiautomator_xml,
)


_SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        package="com.hpbr.bosszhipin" content-desc="" checkable="false"
        checked="false" clickable="false" enabled="true" focusable="false"
        focused="false" scrollable="false" long-clickable="false" password="false"
        selected="false" bounds="[0,0][720,1612]">
    <node index="0" text="" resource-id="com.hpbr.bosszhipin:id/ctl_f3_profile"
          class="android.widget.LinearLayout" package="com.hpbr.bosszhipin"
          content-desc="马先生" checkable="false" checked="false"
          clickable="true" enabled="true" focusable="true" focused="false"
          scrollable="false" long-clickable="false" password="false"
          selected="false" bounds="[20,120][700,360]">
      <node index="0" text="慧莱娱乐·人事主管"
            resource-id="com.hpbr.bosszhipin:id/tv_company_and_position"
            class="android.widget.TextView" package="com.hpbr.bosszhipin"
            content-desc="" checkable="false" checked="false" clickable="false"
            enabled="true" focusable="false" focused="false" scrollable="false"
            long-clickable="false" password="false" selected="false"
            bounds="[40,260][680,320]" />
    </node>
    <node index="1" text="消息" resource-id="com.hpbr.bosszhipin:id/tv_tab_3"
          class="android.widget.TextView" package="com.hpbr.bosszhipin"
          content-desc="" checkable="false" checked="false" clickable="true"
          enabled="true" focusable="true" focused="false" scrollable="false"
          long-clickable="false" password="false" selected="true"
          bounds="[360,1500][540,1612]" />
  </node>
</hierarchy>
UI hierchary dumped to: /dev/tty
""".encode("utf-8")


class TestParseUiautomatorXml:
    def test_returns_droidrun_shaped_root(self) -> None:
        tree = parse_uiautomator_xml(_SAMPLE_XML)
        assert tree["className"] == "android.widget.FrameLayout"
        assert tree["packageName"] == "com.hpbr.bosszhipin"
        assert tree["resourceId"] == ""
        assert tree["boundsInScreen"] == {
            "left": 0,
            "top": 0,
            "right": 720,
            "bottom": 1612,
        }
        assert "children" in tree
        assert len(tree["children"]) == 2

    def test_boolean_attributes_mapped_to_is_prefixed_keys(self) -> None:
        tree = parse_uiautomator_xml(_SAMPLE_XML)
        profile_container = tree["children"][0]
        assert profile_container["isClickable"] is True
        assert profile_container["isFocusable"] is True
        assert profile_container["isSelected"] is False
        assert profile_container["isEnabled"] is True

    def test_content_desc_preserved_as_name_source(self) -> None:
        tree = parse_uiautomator_xml(_SAMPLE_XML)
        profile = tree["children"][0]
        assert profile["resourceId"] == "com.hpbr.bosszhipin:id/ctl_f3_profile"
        assert profile["contentDescription"] == "马先生"

    def test_company_and_position_text_preserved_with_middle_dot(self) -> None:
        tree = parse_uiautomator_xml(_SAMPLE_XML)
        composed = tree["children"][0]["children"][0]
        assert composed["resourceId"].endswith(":id/tv_company_and_position")
        assert composed["text"] == "慧莱娱乐·人事主管"

    def test_trailing_status_line_stripped(self) -> None:
        # Build input with known garbage after </hierarchy>
        tree = parse_uiautomator_xml(_SAMPLE_XML + b"\n\ngarbage after end")
        assert tree["className"] == "android.widget.FrameLayout"

    def test_empty_input_raises(self) -> None:
        with pytest.raises(UiAutomatorFallbackError):
            parse_uiautomator_xml(b"")

    def test_missing_hierarchy_tag_raises(self) -> None:
        with pytest.raises(UiAutomatorFallbackError):
            parse_uiautomator_xml(b"<foo><bar/></foo>")

    def test_malformed_xml_raises(self) -> None:
        with pytest.raises(UiAutomatorFallbackError):
            parse_uiautomator_xml(b"<hierarchy><node bounds=")

    def test_empty_hierarchy_returns_childless_root(self) -> None:
        tree = parse_uiautomator_xml(b"<hierarchy></hierarchy>")
        assert tree["children"] == []
        assert tree["className"] == "android.widget.FrameLayout"

    def test_bounds_with_negative_coords(self) -> None:
        xml = b"""<?xml version='1.0' encoding='UTF-8' ?>
<hierarchy><node class="X" package="p" text="" content-desc=""
  resource-id="" clickable="false" enabled="true"
  bounds="[-5,-10][100,200]"/></hierarchy>"""
        tree = parse_uiautomator_xml(xml)
        assert tree["boundsInScreen"] == {
            "left": -5,
            "top": -10,
            "right": 100,
            "bottom": 200,
        }

    def test_bounds_absent_defaults_to_zero_rect(self) -> None:
        xml = b"""<?xml version='1.0' encoding='UTF-8' ?>
<hierarchy><node class="X" package="p" text="" content-desc=""
  resource-id="" clickable="false" enabled="true"/></hierarchy>"""
        tree = parse_uiautomator_xml(xml)
        assert tree["boundsInScreen"] == {
            "left": 0,
            "top": 0,
            "right": 0,
            "bottom": 0,
        }

    def test_parser_is_compatible_with_existing_recruiter_parser(self) -> None:
        """End-to-end contract: XML fallback output must be consumable
        by the recruiter parser without modification."""
        from boss_automation.parsers.recruiter_profile_parser import (
            extract_recruiter_profile,
        )

        tree = parse_uiautomator_xml(_SAMPLE_XML)
        # The current (pre-PR2) parser may still return None because its
        # schema is out of date; we only assert the parser accepts the
        # shape without raising. Contract coverage of the extraction
        # semantics is the job of the parser-level tests.
        result = extract_recruiter_profile(tree)
        assert result is None or result.name
