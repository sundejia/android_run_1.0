# Contact picker: wrong header tap closed picker (`nma` vs `nmf`)

## Status

Resolved **2026-05-07** (same device/build chain as [contact-picker page-state drift](./2026-05-07-contact-picker-page-state-drift.md)).

## Symptoms

- After **Contact Card**, `SearchContactFinder` logged `could not open search input` even though the contact picker was visibly correct (`Select Contact(s)`, list sections).
- Manual accessibility dumps showed the picker **closed** and the UI returned to **chat** — automation had tapped the **top-right “close” control**, not the magnifier.
- Dry-run E2E (`tests/integration/test_full_image_to_card_dry_run_e2e.py`) failed at the search step before fixes.

## Root cause

On **720×1612** WeCom Android (build observed 2026-05-07), the picker header is:

`… [Search **nmf**] [Close **nma**]`

- **`PICKER_SEARCH_RESOURCE_PATTERNS`** did not include **`nmf`**, so `find_search_button` missed the keyword pass.
- Position fallback picks the **rightmost** header candidate in the top band → **`nma`** (close). Tapping **`nma`** dismisses the picker; no search `EditText` appears in the picker context → failure.

A secondary issue on the same flow: the **confirm-send** modal used **`TextView`** nodes **`de5`** / **`de2`** instead of `Button` + `dak`/`dah`, so `PageStateValidator.is_confirm_send_dialog_open` returned false until those ids were appended to selector tuples.

## Fix

- `src/wecom_automation/services/ui_search/selectors.py`: append **`nmf`** to `PICKER_SEARCH_RESOURCE_PATTERNS`.
- `src/wecom_automation/services/ui_search/ui_helpers.py`: extend `_EXCLUDE_RIDS` with **`nma`** (close), alongside **`nd7`**.
- `src/wecom_automation/services/contact_share/selectors.py`: append **`de5`** / **`de2`** to send/cancel resource patterns for dialog detection.
- Tests: `tests/unit/test_ui_search_helpers.py`, `tests/unit/test_page_state_validator.py`; integration dry-run `tests/integration/test_full_image_to_card_dry_run_e2e.py`.

## References

- Implementation notes: [Contact share reliability (2026-05)](../../implementation/2026-05-07-contact-share-reliability.md)
- Feature: [Auto Contact Share](../../features/auto-contact-share.md)
