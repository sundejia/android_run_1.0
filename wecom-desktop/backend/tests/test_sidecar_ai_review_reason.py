import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))

mock_droidrun = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules["droidrun"] = mock_droidrun
sys.modules["droidrun.tools"] = mock_droidrun.tools
sys.modules["droidrun.tools.adb"] = mock_droidrun.tools.adb

from services.ai_review_details import extract_ai_review_breakdown, extract_ai_review_reason


def test_extract_ai_review_reason_prefers_result_decision_reason():
    payload = {
        "score": 6.0,
        "result": {
            "decision": "合格",
            "decision_reason": "有镜头感、妆发整洁、表情自然，具基本展示吸引力",
            "scores": {
                "anchor_appeal": {"score": 7, "reason": "正脸清晰，眼神专注"},
            },
        },
        "raw_text": "{\"decision_reason\":\"raw fallback\"}",
    }

    reason = extract_ai_review_reason(json.dumps(payload, ensure_ascii=False))

    assert reason == "有镜头感、妆发整洁、表情自然，具基本展示吸引力"


def test_extract_ai_review_reason_falls_back_to_score_reasons_and_penalties():
    payload = {
        "result": {
            "scores": {
                "anchor_appeal": {"score": 7, "reason": "正脸清晰，眼神专注"},
                "image_standard": {"score": 8, "reason": "画面清晰明亮"},
            },
            "penalties": ["聊天截图/拼图/带边框水印"],
        }
    }

    reason = extract_ai_review_reason(json.dumps(payload, ensure_ascii=False))

    assert reason == "正脸清晰，眼神专注；画面清晰明亮；扣分项：聊天截图/拼图/带边框水印"


def test_extract_ai_review_breakdown_returns_score_reasons_and_penalties():
    payload = {
        "result": {
            "scores": {
                "anchor_appeal": {"score": 7, "reason": "正脸清晰，眼神专注"},
                "show_readiness": {"score": 6, "reason": "妆发整洁、着装得体"},
                "image_standard": {"score": 8, "reason": "画面清晰明亮"},
            },
            "penalties": ["聊天截图/拼图/带边框水印"],
        }
    }

    score_reasons, penalties = extract_ai_review_breakdown(json.dumps(payload, ensure_ascii=False))

    assert score_reasons == [
        {
            "key": "anchor_appeal",
            "label": "anchor appeal",
            "score": "7",
            "reason": "正脸清晰，眼神专注",
        },
        {
            "key": "show_readiness",
            "label": "show readiness",
            "score": "6",
            "reason": "妆发整洁、着装得体",
        },
        {
            "key": "image_standard",
            "label": "image standard",
            "score": "8",
            "reason": "画面清晰明亮",
        },
    ]
    assert penalties == ["聊天截图/拼图/带边框水印"]


def test_extract_ai_review_breakdown_normalizes_object_penalties():
    payload = {
        "result": {
            "scores": {
                "anchor_appeal": {"score": 5, "reason": "一般"},
            },
            "penalties": [
                {"reason": "构图偏移", "points": 1},
                {"label": "水印", "description": "角标明显"},
            ],
        }
    }

    _score_reasons, penalties = extract_ai_review_breakdown(json.dumps(payload, ensure_ascii=False))

    assert penalties == ["构图偏移", "水印: 角标明显"]
