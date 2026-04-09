# Type Annotation Fix - PEP 604 Syntax Error

**Date:** 2026-02-01
**Status:** Fixed
**Severity:** High (causes Fatal error on module import)

## Problem

The codebase was experiencing fatal errors when importing modules:

```
Fatal error: unsupported operand type(s) for |: 'builtin_function_or_method' and 'NoneType'
```

This error occurred when using Python 3.10+ union type syntax (`type | None`) without the proper future import.

## Root Cause

Multiple files were using PEP 604 union type syntax (`X | None` instead of `Optional[X]` or `Union[X, None]`) without importing `from __future__ import annotations`.

Without this import, type annotations are evaluated at runtime, which causes the `|` operator to be applied to actual objects (like function objects and `None`), leading to the fatal error.

## Solution

Added `from __future__ import annotations` to all affected files. This import:

1. Defers evaluation of all annotations (stores them as strings)
2. Enables the use of PEP 604 syntax (`|`) without runtime errors
3. Maintains compatibility with older Python versions that don't natively support the syntax

## Files Fixed

### Core Modules (7 files)

- `src/wecom_automation/core/interfaces.py`
- `src/wecom_automation/core/models.py`
- `src/wecom_automation/core/config.py`
- `src/wecom_automation/core/exceptions.py`
- `src/wecom_automation/core/logging.py`
- `src/wecom_automation/core/log_config.py`
- `src/wecom_automation/core/metrics_logger.py`

### Service Layer (12 files)

- `src/wecom_automation/services/adb_service.py`
- `src/wecom_automation/services/sync_service.py`
- `src/wecom_automation/services/timestamp_parser.py`
- `src/wecom_automation/services/wecom_service.py`
- `src/wecom_automation/services/ui_parser.py`
- `src/wecom_automation/services/blacklist_service.py`
- `src/wecom_automation/services/user/avatar.py`
- `src/wecom_automation/services/user/unread_detector.py`
- `src/wecom_automation/services/message/image_storage.py`
- `src/wecom_automation/services/message/processor.py`
- `src/wecom_automation/services/notification/email.py`
- `src/wecom_automation/services/integration/sidecar.py`
- `src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py`

### Sync Module (5 files)

- `src/wecom_automation/services/sync/orchestrator.py`
- `src/wecom_automation/services/sync/checkpoint.py`
- `src/wecom_automation/services/sync/recovery_checkpoint.py`
- `src/wecom_automation/services/sync/factory.py`
- `src/wecom_automation/services/sync/customer_syncer.py`

### Message Handlers (3 files)

- `src/wecom_automation/services/message/handlers/base.py`
- `src/wecom_automation/services/message/handlers/voice.py`
- `src/wecom_automation/services/message/handlers/video.py`

### Database Layer (3 files)

- `src/wecom_automation/database/models.py`
- `src/wecom_automation/database/repository.py`
- `src/wecom_automation/database/schema.py`

**Total:** 30 files fixed

## Example Fix

### Before (causes error)

```python
"""Some module."""

class MyClass:
    def __init__(self):
        self.callback: Callable | None = None  # Runtime error!
```

### After (works correctly)

```python
"""Some module."""

from __future__ import annotations

class MyClass:
    def __init__(self):
        self.callback: Callable | None = None  # No error
```

## Verification

All imports now work correctly:

```bash
uv run python -c "from src.wecom_automation.services.adb_service import ADBService; ..."
# Output: All imports successful!
```

## Lessons Learned

1. **Always use `from __future__ import annotations`** when using PEP 604 syntax (`|` for unions)
2. **Place at the top of the file** (after docstring, before other imports)
3. **Required for class attribute annotations** that use the `|` syntax
4. **Improves compatibility** by deferring annotation evaluation

## Related Documentation

- [PEP 604 – Allow writing union types as X | Y](https://peps.python.org/pep-0604/)
- [PEP 563 – Postponed Evaluation of Annotations](https://peps.python.org/pep-0563/)
