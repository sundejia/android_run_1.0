# FollowUp System Issues Analysis and Fixes

## Overview

This document details the analysis and fixes for three issues reported in the FollowUp system:

1.  **Log Warning**: `Import warning: No module named 'wecom_automation.services.wecom'`
2.  **Init Failure**: `Failed to init sidecar client: cannot access local variable 'sidecarQueueClient'`
3.  **Duplicate Database Entries**: Messages appearing twice in the database (one with timestamp, one without/different) after AI reply.

## Issue 1: Import Warning

### Symptom

Log output:

```
[WARNING] [FOLLOWUP] Import warning: No module named 'wecom_automation.services.wecom', trying alternative paths...
```

### Cause

The standalone script `followup_process.py` attempted to import `WeComService` from `wecom_automation.services.wecom`. However, the correct module name is `wecom_automation.services.wecom_service`.

### Fix

Updated `followup_process.py` to use the correct import path:

```python
# Before
from wecom_automation.services.wecom import WeComService

# After
from wecom_automation.services.wecom_service import WeComService
```

## Issue 2: Sidecar Client Initialization Failure

### Symptom

Log output:

```
[WARNING] [FOLLOWUP] Failed to init sidecar client: cannot access local variable 'sidecarQueueClient' where it is not associated with a value
```

### Cause

In `followup_process.py`, the `SidecarQueueClient` was instantiated without the required `serial` argument:

```python
sidecar_client = SidecarQueueClient()  # Missing serial argument
```

This triggered an error during initialization. The specific `UnboundLocalError: local variable 'sidecarQueueClient' ...` error message likely stems from an exception handler or variable scope issue during the error reporting or fallback process in the runtime environment.

### Fix

Updated `followup_process.py` to pass the device serial to the constructor:

```python
sidecar_client = SidecarQueueClient(args.serial)
```

## Issue 3: Duplicate Database Entries

### Symptom

After an AI reply generates a response, the message appears twice in the database:

1.  One entry containing the correct timestamp.
2.  Another entry (sometimes with missing timestamp data or slight differences).

### Cause

The duplication was caused by redundant saving logic in `response_detector.py`:

1.  **First Save**: The `_send_reply_wrapper` method called the Sidecar API endpoint../03-impl-and-arch/{serial}/send-and-save`. As the name implies, this endpoint sends the message _and_ inserts it into the database.
2.  **Second Save**: Immediately after the message was sent, `response_detector.py` called `_store_sent_message`, which _also_ inserted the message into the database.

Since the two save operations used different methods to generate the message hash (one using UUID, one using content+timestamp), the database treated them as distinct messages.

### Fix

Modified `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` to use the `/send` endpoint instead of `/send-and-save`.

```python
# Before
url = f"http://localhost:87../03-impl-and-arch/{serial}/send-and-save"

# After
url = f"http://localhost:87../03-impl-and-arch/{serial}/send"
```

This ensures the message is sent via the Sidecar API but saved to the database _only_ by the `_store_sent_message` function, consolidating the logic and preventing duplicates.
