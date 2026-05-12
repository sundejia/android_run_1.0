# Auto-blacklist permanently skipped because of missing review data

## Status

Resolved **2026-05-07** (same realtime-reply session that uncovered the [contact-picker page-state drift](./2026-05-07-contact-picker-page-state-drift.md) and [picker search vs close button](./2026-05-07-picker-search-nmf-vs-close-nma.md)).

## Symptoms

After verifying the **detect image → pre-share message → contact card** pipeline works end-to-end on a real device, operators noticed that the **auto-blacklist** action never fired, so AI replies were still being generated for customers who had already sent images.

Realtime log (`logs/AIxiangmuzudeMacBook-Pro.local-10AE9P1DTT002LE.log`) shows the same WARNING for **every** triggering customer:

```
2026-05-07 00:07:39 | WARNING  | logging:callHandlers:1706 |
  Skipping auto-blacklist: review data missing
  (device=10AE9P1DTT002LE, customer=B2604200792-(保底正常),
   message_type=image, message_id=77,
   gate_enabled=False, reason=ai_review_status=None,
   details={'message_id': 77, 'ai_review_status': None,
   'ai_review_error': None})
```

Notice: `gate_enabled=False` (operator never enabled `review_gate`) but the action still demanded an `ai_review_status='completed'` row.

The **next** log line then shows the customer message getting persisted, AI reply generated, and AI reply sent — exactly the behaviour the operator wanted to suppress with auto-blacklist.

## Root cause

`AutoBlacklistAction` was wired in `services/media_actions/factory.py` with the **conversation `db_path`** always injected, and the action's `should_execute` interpreted that as a hard contract:

```python
if self._db_path is not None:
    gate_enabled = bool(settings.get("review_gate", {}).get("enabled", False))
    decision = evaluate_gate_pass(...)
    if not decision.has_data:
        logger.warning("Skipping auto-blacklist: review data missing ...")
        return False
```

`evaluate_gate_pass` returns `has_data=False` whenever the `images.ai_review_status` column is not `'completed'`. On any deployment that has **not** opted into the image-rating-server review pipeline, the column stays `NULL`, so the action skipped **every** media event regardless of whether the operator actually wanted a review-pipeline-aware blacklist.

Two competing semantics had been collapsed into one flag (`db_path is not None`):

1. **"Standalone blacklist"** — *customer sends media → blacklist immediately*. This is the typical product expectation. Most deployments today.
2. **"Gated blacklist"** — *only blacklist customers whose media also passed the rating-server portrait/decision review*. Used when the operator wants `auto_group_invite` and `auto_blacklist` to share one verdict.

Because they were not separable, default behaviour collapsed onto (2) the moment factory wiring passed `db_path`, which is always.

Combined with a **separate** observation in the same log — the realtime AI-reply gate (`response_detector._media_action_handled_keys`) only suppresses AI when `auto_group_invite` or `auto_blacklist` reports `SUCCESS` — the broken auto-blacklist directly defeated AI suppression too: AI replies kept getting generated even though the operator wanted images intercepted.

## Architectural review

Before changing code, the following invariants were re-checked so the fix would not regress the freshly-stabilised contact-share flow:

- **Action ordering** in `factory.py` is `auto_blacklist → auto_group_invite → auto_contact_share` (reordered 2026-05-11; was `auto_contact_share → auto_group_invite → auto_blacklist` at the time of this fix). Blacklist runs **first** so the customer is blocked from AI reply before group invite / contact share execute. ✅ No regression.
- **AI suppression** is owned by `response_detector`:
  - `_on_media_results` adds the customer to `_media_action_handled_keys` whenever any of `{auto_group_invite, auto_blacklist}` reports `ActionStatus.SUCCESS` (line 545-552).
  - The wait loop and the unread-user processor both consult that set before calling AI (lines 1364, 1662).
  - **Cross-round** suppression is also covered: `BlacklistChecker.is_blacklisted(... fail_closed=True)` is consulted in three more places — pre-processing (1155), final send (3143), and reply path (3296).

Once auto-blacklist successfully runs, AI suppression is automatic in **both** the current scan cycle (via `_media_action_handled_keys`) and every later cycle (via persistent blacklist DB rows). No new trigger location is needed.

## Fix

Introduce an explicit **`auto_blacklist.require_review_pass`** flag (default **`False`**). When `False`, the action ignores the rating pipeline entirely; when `True`, the existing gated semantics are preserved.

Files changed:

- `src/wecom_automation/services/media_actions/actions/auto_blacklist.py`
  - `should_execute` now reads `bl_settings.get("require_review_pass", False)` and only consults `evaluate_gate_pass` when both `require_review` is `True` *and* `db_path` is provided.
  - Updated docstring to make the two modes explicit.
- `src/wecom_automation/services/media_actions/settings_loader.py`
  - `DEFAULT_MEDIA_AUTO_ACTION_SETTINGS["auto_blacklist"]["require_review_pass"] = False`.
- `wecom-desktop/backend/services/settings/defaults.py`
  - `SETTING_DEFINITIONS` row for `auto_blacklist` now includes `"require_review_pass": False`.
- `wecom-desktop/backend/routers/media_actions.py`
  - `DEFAULT_SETTINGS["auto_blacklist"]["require_review_pass"] = False` and Pydantic `AutoBlacklistSettings` adds `require_review_pass: bool = False`.
- `wecom-desktop/src/services/api.ts`
  - TypeScript `AutoBlacklistSettings` interface adds `require_review_pass: boolean`.
- `tests/unit/test_auto_blacklist_action.py`
  - Existing `TestAutoBlacklistReviewGate` tests now opt back into the gated path explicitly via `require_review_pass=True`.
  - New `TestAutoBlacklistRequireReviewPassDefault` class locks the standalone-mode contract: image/video media triggers blacklist, evaluator is **not** called, even when `ai_review_status` is `None`.
- `tests/unit/test_media_actions_settings_loader.py`
  - Adds `test_auto_blacklist_default_does_not_require_review_pass`.
- `wecom-desktop/backend/tests/test_media_actions_api.py`
  - Default settings response now asserts `require_review_pass is False`.

## Why the existing trigger position needs no change

The user-level question was *"where should auto-blacklist live so it doesn't break contact-share but still cancels AI replies for media-sending customers?"*. The answer is: **right where it is**, in the same `MediaEventBus`, because:

| concern | covered by |
|---|---|
| contact-share runs first, never blocked by blacklist | `factory.py` registration order |
| current-round AI suppressed when blacklist succeeds | `response_detector._media_action_handled_keys` (line 545+) |
| later-round AI suppressed automatically | `BlacklistChecker.is_blacklisted` at 3 sites in `response_detector` |
| idempotent on re-scan | `should_execute` pre-check via `is_blacklisted_by_name` |

The previous bug was "blacklist never succeeded", not "blacklist was triggered in the wrong place".

## Verification

- `tests/unit/test_auto_blacklist_action.py` — 26 cases, including 6 new ones for the standalone path.
- `tests/unit/test_media_actions_settings_loader.py` — defaults regression locked.
- `tests/unit/test_media_actions_factory.py` — registration order + lifecycle regressions still green.
- `wecom-desktop/backend/tests/test_media_actions_api.py` — API defaults regression locked.
- Full unit suite: 830 passed in 42s.

## Related (2026-05-12)

A **separate** operator-facing pitfall was fixed later: the image-rating-server URL existed in both **System Settings** (`general.image_server_ip`) and the old **Media Auto-Actions** `review_gate.rating_server_url`. Filling only one side left `ai_review_status` unset for the path that read the empty field (for example `Skipping auto-contact-share: review data missing`). Those duplicate fields were removed and migrated; see [Media actions settings dedup (SSOT)](../../implementation/2026-05-12-media-actions-settings-dedup-ssot.md).

## References

- Code: `src/wecom_automation/services/media_actions/actions/auto_blacklist.py`
- Code: `src/wecom_automation/services/media_actions/factory.py`
- Code: `wecom-desktop/backend/services/followup/response_detector.py`
- Feature doc: [Media Auto-Actions](../../features/media-auto-actions.md)
- Related: [Picker search vs close button](./2026-05-07-picker-search-nmf-vs-close-nma.md), [Contact picker page-state drift](./2026-05-07-contact-picker-page-state-drift.md)
