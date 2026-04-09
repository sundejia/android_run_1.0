# 2026-01-24 SidecarQueueClient Not Initialized Error

## Issue Description

Users encountered the following error during the follow-up response detection process:

```
RuntimeError: SidecarQueueClient not initialized. Use 'async with' context manager.
```

This error occurred when the system attempted to use the `SidecarQueueClient` to manage message queues or check skip flags, typically after a reply had been processed or attempted.

## Root Cause Analysis

The issue stemmed from an incorrect lifecycle management of the `SidecarQueueClient` within the `ResponseDetector` class.

1.  **Shared Client Instance**: The `SidecarQueueClient` instance is created in `_scan_device_for_responses` and properly initialized using an `async with` context manager (via `optional_sidecar`). This active client instance is then passed down to helper methods like `_process_unread_user_with_wait` and `_send_reply_wrapper`.

2.  **Premature Session Closure**: In the `_send_reply_wrapper` method, the code redundantly re-entered the context manager for the _same_ client instance:

    ```python
    async with sidecar_client:  # <--- Logic Error
        await sidecar_client.add_message(...)
    ```

3.  **Destructive Exit**: The `SidecarQueueClient.__aenter__` method creates a new `aiohttp.ClientSession` and assigns it to `self._session`. However, `SidecarQueueClient.__aexit__` closes this session and sets `self._session = None`.

4.  **Consequence**: When the `async with` block in `_send_reply_wrapper` finished, it closed the active session. However, the outer scope (in `_scan_device_for_responses`) still held a reference to this client and expected it to be active for subsequent operations (like checking `is_skip_requested` in the next loop iteration). This led to the `RuntimeError` because `self._session` was `None`.

## Solution

The fix involved removing the redundant `async with sidecar_client:` context manager usage in `_send_reply_wrapper`.

### Modified Code (`backend/servic../03-impl-and-arch/response_detector.py`)

```python
async def _send_reply_wrapper(self, ..., sidecar_client: Optional[Any] = None) -> Tuple[bool, Optional[str]]:
    if sidecar_client:
        # 通过 Sidecar 队列发送（需要人工确认）
        try:
            self._logger.info(f"[{serial}] 📡 Routing message to Sidecar queue for {user_name}")

            # REMOVED: async with sidecar_client:

            # Step 1: 添加消息到队列
            msg_id = await sidecar_client.add_message(...)

            # ... rest of the logic ...
```

By removing the inner context manager, the method now correctly uses the existing active session managed by the caller (`_scan_device_for_responses`), preventing premature session closure.

## Verification

- **Static Analysis**: The code flow now guarantees that the `SidecarQueueClient` session remains open for the entire duration of the `_scan_device_for_responses` execution, as intended.
- **Lifecycle Consistency**: The client is opened once at the start of the scan and closed only when the scan finishes or errors out.
