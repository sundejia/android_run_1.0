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
  tests/unit/test_contact_finder_strategy.py tests/unit/test_auto_contact_share_action.py -q
```

Full suite:

```bash
uv run pytest tests/unit/ -q
```

## Related feature doc

See [Auto Contact Share](../features/auto-contact-share.md) for end-user flow, settings, and file map.

## Contact picker search button (magnifier)

After tapping **Contact Card**, `SearchContactFinder` must tap the header search control before typing `contact_name`.

- **Position fallback bug (fixed 2026-05-07)**: `find_search_button` used to restrict header candidates to `bounds.top <= screen_height * 0.08`. On **720×1612**, that is only ~**129px** — real toolbars often place the magnifier lower (status bar + title row). Keyword miss + empty fallback meant **no tap on search**, while users saw the picker open correctly.
- **Fix** (matches `ui_helpers.find_search_button` in code): header fallback uses `bounds[1] <= max(int(screen_height * 0.22), 180)` and `bounds[0] >= screen_width * 0.45`; `find_search_input` prefers search-labelled / upper-screen `EditText` and returns `None` for a lone composer in the lower half so the magnifier path runs first.

## Operational notes

- **Do not swipe the attach grid near screen edges** when debugging manually — same constraint as automation.
- On failure, check **rotated** device log plus **`logs/contact_share_dump_*.json`** (large payloads are intentionally not inlined in `.log` files).
