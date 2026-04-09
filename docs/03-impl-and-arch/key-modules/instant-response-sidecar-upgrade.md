# Instant Response Upgrade Plan: Sidecar Integration

**Objective**: Upgrade the "Instant Response" (Phase 1) feature to send messages via the **Sidecar System** instead of direct ADB execution. This aligns it with the logic used in Full Sync Phase 1.

**Reference**: `src/wecom_automation/services/sync/customer_syncer.py` (Full Sync implementation)

## 1. Context & Motivation

Currently, `ResponseDetector` (Instant Response) directly calls `wecom.send_message()` to reply to customers. This is:

- **Blocking**: The scanner waits for typing/sending.
- **Unsupervised**: Messages are sent immediately without a chance for human review (unless `human_confirmation` logic is hacked in).
- **Inconsistent**: Full Sync uses Sidecar for better control and stability.

**Sidecar** provides:

- A message queue (visible in UI).
- "Ready" state management (draft -> ready -> sent).
- Decoupled execution (backend adds to queue, separate process/UI handles sending).

## 2. Proposed Changes

### 2.1. Backend Service Update (`wecom-desktop/backend/services/followup/service.py` or equivalent follow-up service)

The `FollowUpService` needs to manage `SidecarQueueClient` instances, similar to how it manages the scanner.

- **Add Sidecar Client**: Initialize `SidecarQueueClient` when `start_background_scanner` is called (or processing begins).
- **Config**: Read sidecar settings (enabled, URL).

### 2.2. Response Detector Refactoring (`wecom-desktop/backend/services/followup/response_detector.py`)

Refactor `detect_and_reply` and `_process_unread_user_with_wait` to support Sidecar.

- **Inject Client**: Accept `sidecar_client` in `__init__` or `detect_and_reply`.
- **Replace Send Logic**:
  - _Current_: `wecom.send_message(reply)`
  - _New_:
    ```python
    if use_sidecar:
        msg_id = await sidecar_client.add_message(name, channel, reply)
        await sidecar_client.set_message_ready(msg_id)
        await sidecar_client.wait_for_send(msg_id)
    else:
        wecom.send_message(reply)
    ```
- **Interactive Loop**: Ensure `_interactive_wait_loop` also uses Sidecar for subsequent replies.

### 2.3. Settings Integration

Ensure `FollowUpSettings` includes Sidecar controls (inherited from global Sidecar settings or specific overrides).

- `SidecarSettings` lives in `wecom-desktop/backend/services/settings/models.py` as a dataclass. **Every** key under the SIDECAR category in `defaults.py` (including `sidecar_timeout` and night-mode fields) must be a field on `SidecarSettings`, because `SettingsService.get_sidecar_settings()` uses `SidecarSettings(**data)` from the database.
- `ResponseDetector` should check `settings.sidecar.send_via_sidecar`.

## 3. Detailed Implementation Steps

### Step 1: Update `ResponseDetector`

- Modify `detect_and_reply` signature to accept optional `sidecar_client`.
- Implement private method `_send_reply(content, context)` to encapsulate the branching logic (Sidecar vs Direct).
- Port logic from `CustomerSyncer._send_via_sidecar`.

### Step 2: Update `FollowUpService`

- In `_scan_loop` (or wherever `response_detector` is called), instantiate `SidecarQueueClient` if sidecar is enabled.
- Pass the client to `response_detector`.

### Step 3: Dependencies

- Ensure `aiohttp` reuse or proper session management for `SidecarQueueClient`.

## 4. Risks & Mitigation

- **Performance**: Sidecar might add latency.
  - _Mitigation_: Ensure `wait_for_send` has reasonable timeout.
- **Queue Stalls**: If Sidecar consumer (UI/sender) is offline, scanner might hang.
  - _Mitigation_: Implement timeouts (e.g., 30s) and fallback or skip.

## 5. Verification

- Enable Sidecar in settings.
- Trigger Phase 1 Scan (`enable_instant_response`).
- Verify message appears in Sidecar Queue (UI).
- Verify message is sent and status updates.
