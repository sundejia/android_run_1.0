# Homepage Parsing Exception Fix

> Date: 2026-02-09
> Status: ✅ Resolved
> Severity: P1 (High)
> Related: UI Parser, Sync Service

## Summary

Fixed homepage parsing exceptions caused by incorrect container detection logic. The parser was selecting full-screen root containers that included navigation bars and other non-conversation elements, causing parsing failures.

## Problem

### Symptoms

- Homepage parsing would fail intermittently
- Parser would select root-level containers that covered the entire screen
- These containers included navigation bars, status bars, and other non-conversation elements
- Conversation list detection became unreliable

### Root Cause

The container scoring logic in `ui_parser.py` and `sync_service.py` was:

1. Prioritizing full-width containers (width >= 95% of screen width)
2. Not excluding full-screen root containers (top <= 50px and height >= 95% of screen height)
3. Not considering specific list types (RecyclerView/ListView) over generic ViewGroup
4. Not checking for resourceId presence

This caused the parser to select root containers like:
- Main app containers covering the entire screen
- Navigation containers that included the chat list as a child
- Status bar + title bar + content containers

## Solution

### Changes Made

**Files Modified:**
- `src/wecom_automation/services/ui_parser.py`
- `src/wecom_automation/services/sync_service.py`

**Container Scoring Algorithm Update:**

Before:
```python
def get_container_score(node):
    width = bounds.get("right", 0) - bounds.get("left", 0)
    is_full_width = width >= screen_width * 0.95
    child_count = len(node.get("children") or [])
    return (is_full_width, child_count)
```

After:
```python
def get_container_score(node):
    # 1. Exclude full-screen root containers
    left = bounds.get("left", 0)
    top = bounds.get("top", 0)
    right = bounds.get("right", 0)
    bottom = bounds.get("bottom", 0)
    width = right - left
    height = bottom - top

    is_likely_root = (top <= 50) and (height >= screen_height * 0.95)
    has_margin = not is_likely_root

    # 2. Prefer containers with resourceId
    resource_id = (node.get("resourceId") or "").strip()
    has_resource_id = bool(resource_id)

    # 3. Prefer specific list types (RecyclerView/ListView) over ViewGroup
    class_name = (node.get("className") or "").lower()
    is_specific_list = "recyclerview" in class_name or "listview" in class_name

    # 4. Full-width containers
    is_full_width = width >= screen_width * 0.95

    # 5. Child count
    child_count = len(node.get("children") or [])

    # Priority: has_margin > has_resource_id > is_specific_list > is_full_width > child_count
    return (has_margin, has_resource_id, is_specific_list, is_full_width, child_count)
```

### Scoring Priority (Highest to Lowest)

1. **has_margin** - Excludes full-screen root containers (top <= 50px, height >= 95% screen)
2. **has_resource_id** - Prefers containers with explicit resource IDs
3. **is_specific_list** - RecyclerView/ListView over generic ViewGroup
4. **is_full_width** - Containers spanning most of the screen width
5. **child_count** - More children as a tiebreaker

## Testing

- Unit tests: All 391 tests passing
- Manual verification with real devices confirmed correct container selection
- Parser now correctly identifies conversation list containers

## Related Issues

- None (new issue discovered and fixed)

## References

- Code: `src/wecom_automation/services/ui_parser.py:239-275`
- Code: `src/wecom_automation/services/sync_service.py:503-541`
