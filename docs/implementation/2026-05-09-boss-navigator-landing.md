# BossNavigator Landing — E2E Navigation into Production Code

- **Date**: 2026-05-09
- **Branch**: `fix/boss-e2e-pr2-parser-schema-may2026`
- **Motivation**: Live E2E test proved the data layer works, but navigation fixes
  (BACK-retry tab switching, post-action press_back) only existed in the test
  script (`scripts/boss_e2e_live.py`). This change lands them into production
  code so the project itself can drive the device end-to-end.

## Problem Statement

The May-2026 live E2E test against a real BOSS app on device `10AE9P1DTT002LE`
revealed three gaps in production code:

1. **No `press_back` in AdbPort protocol** — services could not navigate away
   from detail pages (chat detail, resume view, candidate card).
2. **No tab navigation** — `ReplyDispatcher` and `GreetExecutor` assumed the
   device was already on the correct page. After entering a detail screen the
   bottom tab bar disappears, causing all subsequent `tap_by_text` calls to
   fail silently.
3. **No post-action navigation** — after sending a reply or greeting, the
   device was left stranded on a detail page instead of returning to the list.

## Solution: BossNavigator

New service at `src/boss_automation/services/boss_navigator.py` that mirrors
the WeCom `ensure_on_private_chats` / `go_back` pattern but specialized for
the BOSS app's four-tab bottom bar.

### API

```python
class BossNavigator:
    TAB_CANDIDATES = "牛人"
    TAB_MESSAGES   = "消息"
    TAB_ME_CANDIDATES = ("我的", "我")

    async def press_back(self) -> None
    async def navigate_to_tab(self, tab_text: str) -> bool
    async def navigate_to_me_tab(self) -> bool
    async def ensure_on_messages(self) -> bool
    async def ensure_on_candidates(self) -> bool
```

`navigate_to_tab` uses a retry loop: attempt tap, if it returns `False`
(detail page hides tab bar), press BACK and retry.

### Integration Points

| Service | Pre-navigation | Post-navigation |
|---------|---------------|-----------------|
| `ReplyDispatcher` | `ensure_on_messages()` before reading list | `press_back()` after resume view + after send |
| `GreetExecutor` | `ensure_on_candidates()` before parsing feed | `press_back()` after greet |
| `BossAppService` | `navigate_to_me_tab()` for profile detection | N/A (already handled) |
| `boss_messages.py` router | Creates `BossNavigator(adb)`, passes to dispatcher | — |
| `boss_greet.py` router | Creates `BossNavigator(adb)`, passes to executor | — |

## Other Fixes in This Change

### AdbPort Protocol

Added `press_back() -> None` to the `AdbPort` Protocol. `DroidRunAdapter`
implements it via `press_key(4)` with shell `input keyevent 4` fallback.

### DroidRunAdapter `tap_by_text`

Previously called non-existent `AdbTools.tap_by_text()`. Now scans the native
UI tree for matching text bounds and uses `tap_by_coordinates()`.

### DroidRunAdapter `type_text`

Previously called non-existent `AdbTools.type_text()`. Now uses
`AdbTools.input_text()` which handles Chinese via base64-encoded
accessibility service injection.

### DroidRunAdapter `_find_bounds_native` / `_tree_from_structured_elements`

New helper functions that extract element bounds from DroidRun's structured
element list (Part 2 of `get_state()` return tuple), converting them to the
unified UI tree format used by parsers.

## Test Coverage

11 new tests in `tests/unit/boss/services/test_boss_navigator.py`:

- `navigate_to_tab` succeeds on first try
- `navigate_to_tab` retries after BACK press
- `navigate_to_tab` fails after max retries
- `ensure_on_messages` / `ensure_on_candidates` convenience methods
- `press_back` delegates to AdbPort
- `navigate_to_me_tab` succeeds on first candidate ("我的")
- `navigate_to_me_tab` falls back to short label ("我")

All 4 existing FakeAdbPort test classes updated with `press_back`, `tap`,
`type_text` methods to satisfy the updated Protocol.

**Total: 292 BOSS tests pass (was 284 before this change).**

## Files Changed

| File | Change |
|------|--------|
| `src/boss_automation/services/adb_port.py` | Protocol: add `press_back()` |
| `src/boss_automation/services/droidrun_adapter.py` | Implement `press_back`, fix `tap_by_text` with coordinates, fix `type_text` with `input_text`, add `_find_bounds_native`, enhance `_get_state_native` |
| `src/boss_automation/services/boss_navigator.py` | **NEW** — tab-aware navigation service |
| `src/boss_automation/services/boss_app_service.py` | Use Navigator for Me-tab navigation, add `wait_for_login()` |
| `src/boss_automation/services/reply_dispatcher.py` | Pre/post navigation hooks |
| `src/boss_automation/services/greet/greet_executor.py` | Pre/post navigation hooks |
| `wecom-desktop/backend/routers/boss_messages.py` | Wire navigator into dispatch |
| `wecom-desktop/backend/routers/boss_greet.py` | Wire navigator into greet |
| `tests/unit/boss/services/test_boss_navigator.py` | **NEW** — 11 navigator tests |
| `tests/unit/boss/services/test_boss_app_service.py` | FakeAdbPort: add `press_back` |
| `tests/unit/boss/services/test_greet_executor.py` | FakeAdbPort: add `press_back`, `tap` |
| `tests/unit/boss/services/test_reply_dispatcher.py` | FakeAdbPort: add `press_back` |
| `tests/unit/boss/services/test_job_sync_orchestrator.py` | FakeAdbPort: add `press_back`, `tap`, `type_text` |
| `scripts/boss_e2e_live.py` | **NEW** — standalone E2E test script |
