# Contact card auto-share reliability (2026-05)

> **Scope**: `ContactShareService`, `PageStateValidator`, attach-panel selectors, attach-grid swipe geometry, diagnostics, and related unit tests.  
> **Devices referenced**: WeCom Android **720×1612**, build observed **2026-05-06** / **2026-05-07**, serial `10AE9P1DTT002LE`.

## Problem summary

Automatic contact-card sharing could report success when nothing was sent (“fake success”), fail to open the attach panel after tapping `+`, or fail to reach **Contact Card** on the second page of the attachment grid even though the UI showed the correct panel.

Root causes fell into four buckets:

1. **Selector drift** — `resourceId` tokens for the attach button and attach-panel container changed between WeCom builds (`igu`, `aij`, `aif` vs older `i9u`, `ahe`, `aha`).
2. **Over-broad text matching** — substring matching matched chat history or wrong controls (e.g. “Send to:”, “我的名片夹”).
3. **Missing page-state verification** — the flow advanced without proving the expected screen, so later taps hit the wrong layer.
4. **Attach-grid swipe eaten by system gestures** — swipes started and ended **~30px from the left/right edges**, inside Android’s **back/home edge zones**. The OS intercepted the gesture; the GridView never paged, so page 2 (“Contact Card”) never appeared in the accessibility tree.

## What we implemented

### Append-only selector tables (`selectors.py`)

- **Attach button**: `ATTACH_RESOURCE_PATTERNS` includes `igu` (among `i9u`, `id8`); position fallback when patterns miss.
- **Attach panel GridView**: `ATTACH_GRID_RESOURCE_PATTERNS = ("ahe", "aij")` — legacy `ahe` plus **720×1612** build `aij`.
- **Attach item labels** (page-state only): `ATTACH_ITEM_RESOURCE_PATTERNS = ("aha", "aif")` — label nodes are **shared** across all cells; never use these for tapping Contact Card; use **text** patterns only for the card row.

### `PageStateValidator` (`page_state.py`)

After each major UI step, `ContactShareService._assert_page_state` checks whether the tree looks like **attach panel**, **contact picker**, **confirm dialog**, or **chat**. This prevents false advancement when taps miss or the wrong screen is shown. Failure triggers a full UI dump (see below).

### Strict matching (`ui_helpers.py`)

Critical taps (Contact Card row, Send) use **exact** text match modes where substring matching would false-positive.

### Transactional pre-message + recovery (`service.py`)

If configured, the pre-share message is sent first; on failure after that point, an optional **recovery message** can be sent. Dedup / success recording avoids writing “success” when the flow did not complete.

### Diagnostics on Contact Card miss (`service.py`)

If `_open_contact_card_menu` cannot find the Contact Card item after trying the current page and swiping the grid, `_diagnose_contact_card_miss`:

- Re-reads UI and logs nodes whose text/description looks like a card/menu candidate.
- Writes `logs/contact_share_dump_<timestamp>_contact_card_menu.json` with `reason` including `after_swipe=True|False`.

This closed the gap where failures returned **before** `_assert_page_state`, so no dump was produced.

### Contact picker page-state drift (fixed 2026-05-07, post-swipe)

**Symptom:** After Contact Card was tapped, the **contact picker** was visibly on screen (`Select Contact(s)`, list sections like “Company Contacts”), but `_assert_page_state("contact_picker", ...)` failed with `observed=unknown`. Logs showed `fail_contact_card_menu_state_check` and triggered the recovery apology message — same UX as “could not open picker”, yet the UI dump proved the picker **had** opened.

**Cause:** `PageStateValidator.is_contact_picker_open` only recognized legacy picker signatures (`nca` title, `cth` list) plus an **exact** catalog of title strings. On build observed **2026-05-07** (same device `10AE9P1DTT002LE`), WeCom uses **`nle`** for the title row and **`cwa`** for the list container, and the title text is **`Select Contact(s)`** (literal parentheses-s suffix). None of these matched the old predicates.

**Fix:**

- `selectors.py`: append-only **`nle`** / **`cwa`** alongside **`nca`** / **`cth`**.
- `page_state.py`: title fallback matches **`startswith`** prefixes (`Select Contact`, `选择联系人`, …) instead of a brittle exact list — still **not** substring-on-full-tree (avoids “Select All” style false positives).
- Tests: fixtures mirror production dumps; `_assert_page_state` regression test in `test_contact_share_service.py`.

**Non-destructive E2E check:** `scripts/e2e_verify_contact_picker_state.py` (requires `adb forward tcp:<port> tcp:<port>`, DroidRun on device, WeCom on Messages/chat). Asserts `attach_panel` then **`contact_picker`** after opening Contact Card; **does not** tap Send — backs out with `go_back` twice.

### Edge-safe attach-grid swipe (`service.py`)

`_swipe_attach_grid` no longer uses a **30px** inset from both edges (that sat inside OEM edge-gesture regions). It now:

- Insets start/end by **`_ATTACH_SWIPE_EDGE_MARGIN_PX` (100)** from the GridView bounds.
- Uses **`_ATTACH_SWIPE_DURATION_MS` (600)** so the gesture reads as a content scroll, not a fling/back gesture.
- Enforces a minimum swipe distance **`_ATTACH_SWIPE_MIN_DISTANCE_PX` (240)**; on very narrow grids, margin is reduced so distance remains usable.

Evidence: dump `contact_share_dump_20260507_124309_*_contact_card_menu.json` showed **only eight** `aif` labels (page 1) after a “swipe” — the GridView children list matched page 1 only, confirming the swipe did not page until geometry was fixed.

### Scroll contact finder guard (`ui_search/strategy.py`)

`ScrollContactFinder` refuses to scan unless the tree indicates the **contact picker** is open, avoiding taps on the wrong screen.

### Cleanup script

`scripts/cleanup_fake_contact_share_2026_05_06.py` — optional one-off removal of a bad dedup row from `media_action_contact_shares` when SQLite timestamps are stored in UTC (documented in script comments).

## Tests

Relevant unit tests (run from repo root):

```bash
uv run pytest tests/unit/test_contact_share_service.py tests/unit/test_page_state_validator.py \
  tests/unit/test_contact_finder_strategy.py tests/unit/test_auto_contact_share_action.py \
  tests/unit/test_ui_search_helpers.py -q
```

Device smoke (optional — **does not send** a card):

```bash
adb forward tcp:8080 tcp:8080   # match Config droidrun_port
uv run python scripts/e2e_verify_contact_picker_state.py --serial <ADB_SERIAL>
```

Full suite:

```bash
uv run pytest tests/unit/ -q
```

## Related documentation

- [Auto Contact Share](../features/auto-contact-share.md) — end-user flow, settings, and file map.
- [Resolved bug: contact picker page-state drift](../04-bugs-and-fixes/resolved/2026-05-07-contact-picker-page-state-drift.md) — `nle`/`cwa`, `Select Contact(s)`, E2E script.
- [Resolved bug: picker search `nmf` vs close `nma`](../04-bugs-and-fixes/resolved/2026-05-07-picker-search-nmf-vs-close-nma.md) — magnifier vs close button; confirm `de2`/`de5`.

## Contact picker search button (magnifier)

After tapping **Contact Card**, `SearchContactFinder` must tap the header search control before typing `contact_name`.

- **Position fallback bug (fixed 2026-05-07)**: `find_search_button` used to restrict header candidates to `bounds.top <= screen_height * 0.08`. On **720×1612**, that is only ~**129px** — real toolbars often place the magnifier lower (status bar + title row). Keyword miss + empty fallback meant **no tap on search**, while users saw the picker open correctly.
- **Fix** (matches `ui_helpers.find_search_button` in code): header fallback uses `bounds[1] <= max(int(screen_height * 0.22), 180)` and `bounds[0] >= screen_width * 0.45`; `find_search_input` prefers search-labelled / upper-screen `EditText` and returns `None` for a lone composer in the lower half so the magnifier path runs first.

### Wrong magnifier tap — `nma` vs `nmf` (fixed 2026-05-07, second pass)

On **720×1612** (device `10AE9P1DTT002LE`), the contact-picker top bar is laid out as:

`[Back nlc] [Title nle “Select Contact(s)”] [Search **nmf**] [Close **nma**]`

Observed bounds (examples): `nmf` ≈ `528,56,624,152`; `nma` ≈ `624,56,720,152`.

**Symptom:** Keyword lists did not include `nmf`, so `find_search_button` fell through to the **position heuristic**, which picks the **rightmost** candidate in the top-right band — that was **`nma`**, which **closes the picker** and returns to chat. `SearchContactFinder` then reported `could not open search input` even though the picker had been correct.

**Fix (append-only):**

- `src/wecom_automation/services/ui_search/selectors.py`: `PICKER_SEARCH_RESOURCE_PATTERNS` includes **`nmf`** so the keyword pass wins before position fallback.
- `src/wecom_automation/services/ui_search/ui_helpers.py`: `_EXCLUDE_RIDS` includes **`nma`** alongside legacy **`nd7`** so neither close button can be chosen as the “search” control.

Regression: `tests/unit/test_ui_search_helpers.py` (`test_prefers_nmf_over_nma_on_2026_05_07_picker`, `test_excludes_nma_close_button_2026_05_07_build`).

### Confirm-send dialog — `TextView` + `de2` / `de5` (fixed 2026-05-07, third pass)

After selecting a contact, WeCom shows “Send to: …” with **Send** and **Cancel**. On the same build, those controls are **`android.widget.TextView`** nodes with resource ids **`de5`** (Send) and **`de2`** (Cancel), not `android.widget.Button` and not the legacy **`dak`** / **`dah`** pair.

**Symptom:** `PageStateValidator.is_confirm_send_dialog_open` stayed **false** (no Button-class match; no dak/dah resource match), while the dialog was visibly open — dry-run E2E could tap Cancel but failed the “dialog present” assertion.

**Fix:** `src/wecom_automation/services/contact_share/selectors.py` — append **`de5`** to `SEND_RESOURCE_PATTERNS`, **`de2`** to `CANCEL_RESOURCE_PATTERNS` (fallback branch in `page_state.py` already supports send+cancel rid co-presence).

Regression: `tests/unit/test_page_state_validator.py` (`test_recognized_via_de2_de5_textview_2026_05_07_build`).

### Full pipeline dry-run E2E (no messages sent)

Script **`tests/integration/test_full_image_to_card_dry_run_e2e.py`** exercises:

1. `AutoContactShareAction.should_execute` + `render_media_template` (simulated `MediaEvent`).
2. Real device: attach → Contact Card → **`nmf`** search → select contact → assert confirm dialog (**de2/de5**) → **Cancel** only (no Send).

Requires ADB + DroidRun + WeCom; contact name must exist in org directory.

```bash
.venv/bin/python tests/integration/test_full_image_to_card_dry_run_e2e.py \
  --serial <ADB_SERIAL> --port 8080 --contact "<searchable name>"
```

## Operational notes

- **Do not swipe the attach grid near screen edges** when debugging manually — same constraint as automation.
- On failure, check **rotated** device log plus **`logs/contact_share_dump_*.json`** (large payloads are intentionally not inlined in `.log` files).
