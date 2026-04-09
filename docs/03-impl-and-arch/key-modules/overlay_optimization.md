# DroidRun Overlay Optimization

This document describes the comprehensive optimizations implemented for the DroidRun overlay feature, which displays numbered overlays on UI elements corresponding to indices in `clickable_elements_cache`.

## Overview

The DroidRun overlay feature shows numbers on clickable UI elements. These numbers correspond to indices in the `clickable_elements_cache` - a pre-processed, flat list of all interactive elements. Our optimizations leverage this architecture for:

1. **Reduced ADB calls** - Single `get_state()` instead of multiple calls
2. **Skip recursion** - Flat list doesn't need recursive child search
3. **O(1) lookups** - Text indexing for instant element finding
4. **Change detection** - Hash-based detection to skip re-parsing unchanged UI
5. **Cache with TTL** - Avoid redundant state fetches within time window
6. **DroidRun integration** - Store overlay indices for reliable tap operations

## Implementation Summary

### TDD Approach

All optimizations were implemented following Test-Driven Development (TDD):

1. **RED** - Write failing tests first
2. **GREEN** - Implement minimal code to pass tests
3. **REFACTOR** - Clean up while keeping tests green
4. **COMMIT** - Commit only when all tests pass

**Total: 320 unit tests, 11 commits**

---

## 1. UIStateCache with TTL-Based Invalidation

### Location

`src/wecom_automation/services/adb_service.py`

### Description

A dataclass that caches all UI state data with time-to-live (TTL) based validity checking. The cache is automatically invalidated after any UI-modifying operation.

### Code

```python
@dataclass
class UIStateCache:
    """Cache for DroidRun UI state with TTL-based invalidation."""
    formatted_text: str = ""
    focused_text: str = ""
    raw_tree: Any = None
    clickable_elements: List[Dict[str, Any]] = field(default_factory=list)
    tree_hash: str = ""
    text_index: Dict[str, Dict] = field(default_factory=dict)
    timestamp: float = 0.0

    def is_valid(self, ttl_seconds: float = 0.5) -> bool:
        """Check if cache is still fresh (within TTL)."""
        if self.timestamp == 0.0:
            return False
        return (time.time() - self.timestamp) < ttl_seconds

    def invalidate(self) -> None:
        """Force cache to be refreshed on next query."""
        self.timestamp = 0.0
```

### Auto-Invalidation

Cache is automatically invalidated after these operations:

- `tap()`, `tap_coordinates()`
- `swipe()`
- `input_text()`
- `press_enter()`, `press_back()`
- `start_app()`
- `clear_text_field()`

---

## 2. Unified State Fetching

### Location

`src/wecom_automation/services/adb_service.py`

### Description

Methods to fetch both UI tree and clickable elements in a single `get_state()` call, avoiding redundant ADB communication.

### Methods

```python
async def get_ui_state(self, force: bool = False) -> Tuple[Optional[Any], List[Dict[str, Any]]]:
    """Get both UI tree and clickable elements in a single get_state() call."""

async def refresh_state(self, force: bool = False) -> UIStateCache:
    """Refresh UI state and return the cache object."""

async def get_ui_tree(self, refresh: bool = True) -> Optional[Any]:
    """Get UI tree with optional cache usage."""

async def get_clickable_elements(self, refresh: bool = True) -> List[Dict[str, Any]]:
    """Get clickable elements with optional cache usage."""
```

### Usage

```python
# Before: Two ADB calls
tree = await adb.get_ui_tree()
elements = await adb.get_clickable_elements()

# After: Single ADB call
tree, elements = await adb.get_ui_state()
```

---

## 3. Hash-Based Change Detection

### Location

`src/wecom_automation/services/adb_service.py`

### Description

Generate deterministic hashes of UI trees to detect when the UI has changed. Useful for detecting when scrolling has reached the end or when an action didn't change the UI.

### Methods

```python
def hash_ui_tree(self, tree: Any) -> str:
    """Generate a deterministic hash for UI tree comparisons."""

def is_tree_unchanged(self) -> bool:
    """Check if UI tree matches previous hash (skip re-parsing optimization)."""
```

### Usage

```python
# Detect scroll end
await adb._refresh_ui_state()
if adb.is_tree_unchanged():
    print("Reached end of list - UI didn't change after scroll")
```

---

## 4. Text Indexing for O(1) Lookups

### Location

`src/wecom_automation/services/adb_service.py`

### Description

Build a dictionary mapping lowercase text to clickable elements, enabling instant O(1) lookups instead of O(n) list traversal.

### Methods

```python
def _build_text_index(self) -> Dict[str, Dict]:
    """Build text index from clickable elements for O(1) lookup."""

def find_by_text_indexed(self, text: str) -> Optional[Dict[str, Any]]:
    """O(1) lookup of element by text using text index."""
```

### Usage

```python
# Before: O(n) search
for element in elements:
    if element.get("text", "").lower() == "messages":
        return element

# After: O(1) lookup
element = adb.find_by_text_indexed("Messages")
```

---

## 5. Direct Index Access Methods

### Location

`src/wecom_automation/services/adb_service.py`

### Description

Methods for direct element access by index or pattern matching on the flat clickable elements cache.

### Methods

```python
def get_element_by_index(self, index: int) -> Optional[Dict[str, Any]]:
    """Get a clickable element directly by its DroidRun overlay index."""

async def find_clickable_by_text(
    self, patterns: Tuple[str, ...], exact: bool = False
) -> Optional[Dict[str, Any]]:
    """Find a clickable element by text patterns (no recursion)."""

async def find_clickable_by_resource_id(
    self, patterns: Tuple[str, ...]
) -> Optional[Dict[str, Any]]:
    """Find a clickable element by resource ID patterns (no recursion)."""
```

### Usage

```python
# Get element by overlay number
element = adb.get_element_by_index(5)

# Find by text patterns
send_btn = await adb.find_clickable_by_text(("Send", "发送"))

# Find by resource ID
input_field = await adb.find_clickable_by_resource_id(("edit", "input"))
```

---

## 6. Convenience Tap Methods

### Location

`src/wecom_automation/services/adb_service.py`

### Description

High-level tap methods that follow DroidRun's best practice of refreshing state before tapping.

### Methods

```python
async def tap_by_index(self, index: int, refresh_first: bool = True) -> str:
    """Refresh state and tap element by index in one call."""

async def tap_element(self, element: Dict[str, Any]) -> str:
    """Tap using an element dictionary."""
```

### Usage

```python
# DroidRun best practice: refresh + tap
await adb.tap_by_index(5)

# Tap element from search result
element = await adb.find_clickable_by_text(("Send",))
if element:
    await adb.tap_element(element)
```

---

## 7. Type-Specific Element Helpers

### Location

`src/wecom_automation/services/adb_service.py`

### Description

Convenience methods for filtering elements by Android widget type.

### Methods

```python
def get_elements_by_type(self, class_name_contains: str) -> List[Dict[str, Any]]:
    """Get elements filtered by class name."""

def get_buttons(self) -> List[Dict[str, Any]]:
    """Get all button elements (Button, ImageButton)."""

def get_text_fields(self) -> List[Dict[str, Any]]:
    """Get all text input field elements (EditText)."""

def get_image_views(self) -> List[Dict[str, Any]]:
    """Get all image view elements (ImageView)."""
```

### Usage

```python
# Find all buttons
buttons = adb.get_buttons()

# Find input fields
text_fields = adb.get_text_fields()

# Custom type filter
recycler_views = adb.get_elements_by_type("RecyclerView")
```

---

## 8. Debug Utilities

### Location

`src/wecom_automation/services/adb_service.py`

### Description

Properties and methods for debugging and understanding the current UI state.

### Properties & Methods

```python
@property
def last_formatted_text(self) -> str:
    """Get the formatted text from the last get_state() call."""

@property
def last_focused_text(self) -> str:
    """Get the focused element text from the last get_state() call."""

def log_ui_summary(self, max_elements: int = 20) -> None:
    """Log a comprehensive UI state summary for debugging."""
```

### Usage

```python
# Debug current state
adb.log_ui_summary()

# Check formatted text
print(adb.last_formatted_text)
```

---

## 9. UIParser Flat-List Optimization

### Location

`src/wecom_automation/services/ui_parser.py`

### Description

Added `is_flat_list` parameter to skip unnecessary recursive child searches when working with the flat `clickable_elements_cache`.

### Methods

```python
def find_element_by_text(
    self,
    elements: List[Dict[str, Any]],
    text_patterns: Tuple[str, ...],
    exact_match: bool = False,
    is_flat_list: bool = False,  # NEW
) -> Optional[Dict[str, Any]]:
    """Find element with optional recursion skip."""

def find_all_elements_by_text(
    self,
    elements: List[Dict[str, Any]],
    text_patterns: Tuple[str, ...],
    exact_match: bool = False,
    is_flat_list: bool = False,  # NEW
) -> List[Dict[str, Any]]:
    """Find all elements with optional recursion skip."""

def match_user_to_index(
    self,
    user: UserDetail,
    clickable_elements: List[Dict[str, Any]],
) -> Optional[int]:
    """Find the DroidRun index for a user by matching text."""
```

### Usage

```python
# Optimized for flat list (no recursion)
element = parser.find_element_by_text(
    clickable_elements,
    ("Messages",),
    is_flat_list=True
)

# Match user to overlay index
index = parser.match_user_to_index(user, clickable_elements)
if index is not None:
    await adb.tap(index)
```

---

## 10. WeComService Optimization

### Location

`src/wecom_automation/services/wecom_service.py`

### Description

Updated helper methods to use `is_flat_list=True` and `get_ui_state()` for optimized performance.

### Optimized Methods

```python
def _find_input_field(self, elements: List[Dict], is_flat_list: bool = False):
    """Find input field with optional recursion skip."""

def _find_send_button(self, elements: List[Dict], is_flat_list: bool = False):
    """Find send button with optional recursion skip."""

def _find_user_element(
    self, elements: List[Dict], user_name: str, channel: Optional[str],
    is_flat_list: bool = False
):
    """Find user element with optional recursion skip."""

async def go_back(self):
    """Navigate back using get_ui_state() (single ADB call)."""

async def send_message(self, text: str):
    """Send message using get_ui_state() (single ADB call)."""
```

### Before vs After

```python
# Before: Multiple ADB calls
async def go_back(self):
    ui_tree = await self.adb.get_ui_tree()
    clickable_elements = await self.adb.get_clickable_elements()
    ...

# After: Single ADB call
async def go_back(self):
    ui_tree, clickable_elements = await self.adb.get_ui_state()
    ...
```

---

## 11. Data Model Enhancement

### Location

`src/wecom_automation/core/models.py`

### Description

Added `droidrun_index` field to `UserDetail` for storing the DroidRun overlay index, enabling reliable tap operations.

### Changes

```python
@dataclass
class UserDetail:
    name: str
    channel: Optional[str] = None
    last_message_date: Optional[str] = None
    message_preview: Optional[str] = None
    avatar: Optional[AvatarInfo] = None
    droidrun_index: Optional[int] = None  # NEW

    def to_dict(self) -> Dict[str, Any]:
        return {
            ...
            "droidrun_index": self.droidrun_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserDetail":
        """Create UserDetail from dictionary."""
        ...
```

### Usage

```python
# Create user with index
user = UserDetail(name="wgz", droidrun_index=5)

# Tap user by stored index
if user.droidrun_index is not None:
    await adb.tap(user.droidrun_index)

# Serialize/deserialize
data = user.to_dict()
user2 = UserDetail.from_dict(data)
```

---

## Performance Benefits

| Optimization   | Benefit                                               |
| -------------- | ----------------------------------------------------- |
| UIStateCache   | Avoid redundant `get_state()` calls within TTL window |
| get_ui_state() | Single ADB call instead of two                        |
| Hash detection | Skip re-parsing when UI unchanged                     |
| Text indexing  | O(1) lookup instead of O(n) search                    |
| is_flat_list   | Skip recursive traversal on flat lists                |
| droidrun_index | Reliable tapping without re-searching                 |

## Test Coverage

| Component              | Tests         |
| ---------------------- | ------------- |
| UIStateCache           | 20 tests      |
| Unified State Fetching | 14 tests      |
| Hash Detection         | 13 tests      |
| Text Indexing          | 13 tests      |
| Index Access           | 17 tests      |
| Tap Methods            | 9 tests       |
| Type Helpers           | 10 tests      |
| Debug Utils            | 9 tests       |
| UIParser Flat-List     | 11 tests      |
| WeComService           | 8 tests       |
| Data Models            | 9 tests       |
| **Total**              | **320 tests** |

## Git Commits

```
7b5f959 feat(models): add droidrun_index field to UserDetail
14a3329 feat(wecom): optimize WeComService with flat-list and get_ui_state()
60c79af feat(ui_parser): add flat-list optimization and index matching
d973209 feat(adb): add debug utilities
c61bdca feat(adb): add type-specific element helpers
48e0284 feat(adb): add convenience tap methods
80cf503 feat(adb): add direct index access methods
4cc903f feat(adb): add O(1) text indexing for user lookup
2ea8e99 feat(adb): add hash-based change detection
01099a5 feat(adb): add unified state fetching with refresh control
8006648 feat(adb): add UIStateCache with TTL-based invalidation
```
