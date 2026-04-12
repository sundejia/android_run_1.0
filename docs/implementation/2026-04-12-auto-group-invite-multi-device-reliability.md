# Auto group invite: multi-WeCom-version and multi-resolution reliability

> **Status**: Implemented and validated on three physical devices (2026-04-12)  
> **Related**: [Media auto-actions](../features/media-auto-actions.md), [Android group invite workflow](2026-04-04-android-group-invite-workflow.md)

## Problem

Automatic group creation (triggered when a customer sends an image or video) failed on three different phone models. Initial hypothesis was **UI tree / resource-ID fragmentation** across WeCom builds. Diagnostics showed that was only part of the story:

- **WeCom versions** differed (e.g. 5.0.3, 5.0.6, 5.0.7): message-row `resourceId` values for avatars, timestamps, and media did **not** match legacy hardcoded IDs on any device.
- **Screen geometry** differed (e.g. 1080×2400 vs 1080×2340): **hardcoded pixel bounds** in `WeComService` broke tap targets and scroll heuristics on non-reference devices.

## Approach

1. **Evidence**: `scripts/diagnose_group_invite.py` — enumerate online ADB devices, capture WeCom version, resolution, flattened UI samples, and selector match hints; write timestamped reports under `diagnostic_reports/` (gitignored; see `diagnostic_reports/README.md`).
2. **Message classification without fragile RIDs**: `services/ui_parser.py` — detect image / video / voice / sticker / timestamp using **bounds geometry**, class names, text regex (e.g. voice duration, time-like strings), and simple parent/child structure instead of version-specific `resourceId` fragments.
3. **Broader group-invite selectors**: `services/group_invite/selectors.py` — expand text, `contentDescription`, and `resourceId` **patterns** for chat info menu, add member, search, confirm, and group name so more locales and WeCom builds match.
4. **Resolution-aware automation**: `services/wecom_service.py` — `_ensure_screen_resolution()` reads physical resolution and scales **scroll / swipe** (`ScrollConfig`) from a **1080×2340 reference**; group-invite steps call `_update_screen_dimensions()` on each UI dump (root bounds) and use **ratio-based** geometry for icon-only controls (720p / 1080p validated; see [bug note](../bugs/2026-04-12-multi-resolution-group-invite-and-droidrun-port-fix.md)); **retries + structured logging** on `open_chat_info`, `tap_add_member_button`, `search_and_select_member`, `confirm_group_creation`.
5. **Scroll coordinates**: base values live on `ScrollConfig` in `core/config.py`; `WeComService` scales them when the device resolution is known (`_apply_resolution_to_scroll_config`) so list scrolling stays consistent across heights.

## Validation

- **Unit tests**: existing suites for `ui_parser`, `WeComService` screen detection, group invite workflow, `GroupChatService`, media event bus, and auto-group-invite action were updated or kept green as APIs evolved.
- **Real devices** (2026-04-12): helper scripts (tracked as `scripts/run_group_invite_*.py`, not `test_*.py` — see repo `.gitignore`) verified:
  - `run_group_invite_quick.py --all` — first visible customer, open info, add-member, then back (no group created).
  - `run_group_invite_full.py` per serial — full flow including search member **孙德家** and confirm; **3/3 devices PASS**.

## Operational notes

- **`navigate_to_chat` / list click**: customer rows often show **full display text** (e.g. `B2604110012-(备注后缀)`). `_find_user_element` still uses **exact** text match; production paths should pass the same string the UI shows (as stored in conversation metadata). The `run_group_invite_*` scripts pick the first on-screen row starting with `B2` for smoke tests.
- **`POST /api/media-actions/test-trigger`**: still does **not** attach a real `WeComService`; it records intent only for group invite. True UI validation must use sync/realtime paths or the `run_group_invite_*` scripts with ADB.

## Files touched (summary)

| Area | Path |
|------|------|
| Diagnostics | `scripts/diagnose_group_invite.py`, `diagnostic_reports/README.md` |
| Parser | `src/wecom_automation/services/ui_parser.py` |
| Selectors | `src/wecom_automation/services/group_invite/selectors.py` |
| UI automation | `src/wecom_automation/services/wecom_service.py` |
| Manual E2E | `scripts/run_group_invite_e2e.py`, `run_group_invite_quick.py`, `run_group_invite_full.py` |

Scroll pixel coordinates from `ScrollConfig` are **scaled at runtime** in `WeComService` after the device resolution is read (`_apply_resolution_to_scroll_config`).

## Maintenance

When a new WeCom build breaks detection:

1. Run `diagnose_group_invite.py` on a failing device and inspect the raw JSON for unmatched controls.
2. Prefer extending **text/desc/bounds heuristics** in `selectors.py` / `WeComService` over adding new obfuscated `resourceId` literals unless unavoidable.
