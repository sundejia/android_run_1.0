# Contact picker page-state false negative (2026-05-07)

## Symptoms

- After customer sent image/video, **auto contact share** ran, **+** and **Contact Card** appeared to work, but the flow aborted with:
  - `[state-check contact_card_menu] FAILED — expected=contact_picker observed=unknown`
  - Metric / result: `fail_contact_card_menu_state_check`
- A recovery apology message was sent; the actual business card was not shared.
- UI dumps (e.g. `logs/contact_share_dump_*_contact_card_menu.json`) showed the **real** contact picker: title `Select Contact(s)` with resourceId ending in `nle`, list `cwa` — not the legacy `nca` / `cth` pair the validator only knew about.

## Root cause

1. **Resource ID drift** on a newer WeCom build: contact picker title list used `nle` instead of `nca`, list container `cwa` instead of `cth`.
2. **Title text drift**: exact-match fallback only listed forms like `Select Contact`, not the plural `Select Contact(s)` with a literal `(s)` suffix.
3. `PageStateValidator.is_contact_picker_open` therefore returned `False` even when the picker was on screen, so `_assert_page_state("contact_picker", ...)` failed after a successful Contact Card tap.

## Fix (code)

- `selectors.py`: append-only `CONTACT_PICKER_TITLE_RESOURCE` → `("nca", "nle")`, `CONTACT_PICKER_LIST_RESOURCE` → `("cth", "cwa")`.
- `page_state.py`: title text fallback uses **prefix** match for `Select Contact` / `选择联系人` (covers `Select Contact(s)`); avoids over-broad substring matching.
- Unit tests: fixtures from production dumps; `ContactShareService._assert_page_state` integration test for the new build.
- **E2E verification script** (device + DroidRun): `scripts/e2e_verify_contact_picker_state.py` — opens chat, attach panel, Contact Card, asserts `contact_picker` without sending the card (backs out before Send).

## References

- Implementation detail: [Contact share reliability (2026-05)](../../implementation/2026-05-07-contact-share-reliability.md)
- Feature flow: [Auto Contact Share](../../features/auto-contact-share.md)
