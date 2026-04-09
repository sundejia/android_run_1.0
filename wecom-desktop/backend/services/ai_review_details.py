"""Parse image-rating-server details JSON for API responses (Sidecar, customers, etc.)."""

from __future__ import annotations

import json
from typing import Dict, List, Optional


def _normalize_penalty_item(item: object) -> Optional[str]:
    """Penalties may be plain strings or objects from the rating API."""
    if item is None:
        return None
    if isinstance(item, str):
        s = item.strip()
        return s or None
    if isinstance(item, (int, float, bool)):
        return str(item)
    if not isinstance(item, dict):
        return str(item).strip() or None

    label_v = item.get("label")
    desc_v = item.get("description")
    label_s = label_v.strip() if isinstance(label_v, str) else ""
    desc_s = desc_v.strip() if isinstance(desc_v, str) else ""
    if label_s and desc_s:
        return f"{label_s}: {desc_s}"

    keys = (
        "reason",
        "description",
        "message",
        "text",
        "deduction_reason",
        "detail",
        "summary",
        "label",
        "name",
        "title",
        "content",
        "penalty",
    )
    for key in keys:
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    label = item.get("label")
    reason = item.get("reason")
    ls = label.strip() if isinstance(label, str) else ""
    rs = reason.strip() if isinstance(reason, str) else ""
    if ls and rs and ls != rs:
        return f"{ls}: {rs}"
    if rs:
        return rs
    if ls:
        return ls

    for val in item.values():
        if isinstance(val, str) and val.strip():
            return val.strip()

    try:
        return json.dumps(item, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _normalize_penalty_list(raw: object) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        s = _normalize_penalty_item(item)
        if s:
            out.append(s)
    return out


def extract_ai_review_reason(details_json: Optional[str]) -> Optional[str]:
    """Pick a human-readable reason string from analysis details JSON."""
    if not details_json:
        return None
    try:
        data = json.loads(details_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    def _pick_text(payload: object, *keys: str) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        for key in keys:
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    direct_reason = _pick_text(data, "decision_reason", "reason", "explanation", "summary", "message", "analysis")
    if direct_reason:
        return direct_reason

    result = data.get("result")
    nested_reason = _pick_text(
        result,
        "decision_reason",
        "reason",
        "explanation",
        "summary",
        "message",
        "analysis",
    )
    if nested_reason:
        return nested_reason

    if isinstance(result, dict):
        score_reasons: List[str] = []
        scores = result.get("scores")
        if isinstance(scores, dict):
            for item in scores.values():
                if isinstance(item, dict):
                    reason = _pick_text(item, "reason")
                    if reason and reason not in score_reasons:
                        score_reasons.append(reason)

        penalties = result.get("penalties")
        if isinstance(penalties, list):
            penalty_text = "；".join(_normalize_penalty_list(penalties))
            if penalty_text:
                score_reasons.append(f"扣分项：{penalty_text}")

        if score_reasons:
            return "；".join(score_reasons)

    raw_text = data.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        try:
            raw_data = json.loads(raw_text)
        except json.JSONDecodeError:
            raw_data = None
        raw_reason = _pick_text(raw_data, "decision_reason", "reason", "explanation", "summary", "message", "analysis")
        if raw_reason:
            return raw_reason

    return None


def extract_ai_review_breakdown(details_json: Optional[str]) -> tuple[List[Dict[str, str]], List[str]]:
    """Return structured score reasons and penalties from analysis details JSON."""
    if not details_json:
        return [], []
    try:
        data = json.loads(details_json)
    except json.JSONDecodeError:
        return [], []
    if not isinstance(data, dict):
        return [], []

    result = data.get("result") if isinstance(data.get("result"), dict) else data
    if not isinstance(result, dict):
        return [], []

    score_reasons: List[Dict[str, str]] = []
    scores = result.get("scores")
    if isinstance(scores, dict):
        for key, item in scores.items():
            if not isinstance(item, dict):
                continue
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                continue
            label = str(key).strip().replace("_", " ")
            score_value = item.get("score")
            score_text = ""
            if score_value is not None:
                score_text = str(score_value).strip()
            score_reasons.append(
                {
                    "key": str(key),
                    "label": label,
                    "score": score_text,
                    "reason": reason.strip(),
                }
            )

    penalties: List[str] = []
    raw_penalties = result.get("penalties")
    if isinstance(raw_penalties, list):
        penalties = _normalize_penalty_list(raw_penalties)

    return score_reasons, penalties
