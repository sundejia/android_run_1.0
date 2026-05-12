# New-friend false positives, click-loop guardrails, and photo-rate remediation (2026-05-12)

## Summary

Production logs (2026-05-05 / 06 / 09 / 10) showed a collapsing “photo rate” funnel: the system spent hours stuck on a single mis-prioritised customer (`NewFriend: True` on agent copy like「感谢您的考虑」), click failures, and cooldown loops. This change set tightens detection, adds a day-level click blocklist, relaxes list matching for truncated or full-width UI text, and persists **click-health** samples for monitoring.

## Delivered changes

| Area | Change |
|------|--------|
| **P1 Keywords** | Removed the over-broad substring `感谢您` from new-friend welcome detection; aligned `NEW_FRIEND_WELCOME_KEYWORDS` between `sync_service.UnreadUserExtractor` and `user.unread_detector.UnreadUserExtractor`; parity + negative cases in `tests/unit/test_new_friend_welcome_keywords.py`. |
| **P2 Dayblock** | `ResponseDetector`: `_click_dayblock` keyed by `{serial}:{name}`, filled after N consecutive click failures (default 5); filtered in `_detect_first_page_unread` so blocked users never occupy the priority queue; day rollover clears block + counters; `click_runaway` metric on escalation; replay test caps repeated processing. |
| **P3 Click match** | `WeComService._find_user_element`: tiered match (exact → normalised full-width/ellipsis → truncated prefix for long names only); `click_user_in_list` uses `max(config.scroll.max_scrolls, _CLICK_USER_MIN_SCROLLS)` with floor 10. Tests: `tests/unit/test_wecom_service_user_match.py`. |
| **P4 Monitoring** | `monitoring.db` table `click_health`; `record_click_health` + queries in `heartbeat_service.py`; `GET /api/monitoring/click-health` and `GET /api/monitoring/click-health/latest` (filter `?device_serial=`); per-scan write from `realtime_reply_process.py`; snapshot fields include `unique_customers_clicked`, `priority_queue_repeats`. Doc: `docs/03-impl-and-arch/key-modules/click-health-monitoring.md`. |

## Primary files

- `src/wecom_automation/services/sync_service.py`
- `src/wecom_automation/services/user/unread_detector.py`
- `src/wecom_automation/services/wecom_service.py`
- `wecom-desktop/backend/services/followup/response_detector.py`
- `wecom-desktop/backend/services/heartbeat_service.py`
- `wecom-desktop/backend/routers/monitoring.py`
- `wecom-desktop/backend/scripts/realtime_reply_process.py`

## Regression tests

- `tests/unit/test_new_friend_welcome_keywords.py`
- `tests/unit/test_wecom_service_user_match.py`
- `wecom-desktop/backend/tests/test_response_detector_click_dayblock.py`
- `wecom-desktop/backend/tests/test_monitoring_click_health.py`

## Related bug write-up

- [Resolved RCA: new-friend false positive + click loop](../04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md)
