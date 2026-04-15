# Sidecar 超时与重复发送问题分析

> 创建于：2026-02-09  
> 状态：🔴 进行中（根因已明确，待修复）  
> 严重性：P1（高）  
> 相关：FollowUp Sidecar、补刀/回复发送流程

> **Documentation note (2026-04-15):** Default daytime Sidecar review wait is now **60 s** (`sidecar_timeout`). This write-up still describes behaviour when callers used **300 s**; see [Sidecar review timeout defaults](../../sidecar/sidecar-review-timeout-defaults.md).

## 摘要

在较旧或性能较差的设备上，出现两类现象：

1. **Sidecar 界面不出现倒计时、输入框不显示消息**：日志中已有 "Message ready for send"，但用户看不到倒计时和消息内容。
2. **同一条消息被发送两次**：先因 "Sidecar send failed: timeout" 走直接发送，随后又通过 Sidecar 队列发送，导致重复消息。

本文档总结根因分析与建议修复方案。

---

## 问题 1：Sidecar 不出现倒计时和消息

### 现象

- 日志中有 `[AI] Message ready for xxx`（由前端 `SidecarView.vue` 的 `addDeviceLog` 输出）。
- 用户侧：倒计时不出现，输入框没有待发消息。

### 流程简述

1. 后端将消息加入队列并 `set_message_ready()`，开始 `wait_for_send(msg_id, timeout=...)`（当时多为 300；现为可配置，默认 60）。
2. 前端每 `pollIntervalMs`（默认 10 秒）轮询 `GET /sidecar/{serial}/queue`。
3. 当检测到 `status === 'ready'` 时，设置 `panel.pendingMessage`、`panel.currentQueuedMessage`，并满足条件时调用 `startCountdown(serial, true)`。
4. 倒计时由 `SidecarView.vue` 的 `startCountdown` 启动，到期后调用 `sendNow` → `sendQueuedMessage`。

### 可能原因

| 原因                  | 说明                                                                                                                                                                                                  |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. 轮询延迟**       | 旧设备/网络下，前端轮询间隔或请求延迟大，用户看到 "Message ready" 时已接近后端 300s 超时，倒计时时间很短或几乎看不到。                                                                                |
| **B. 状态阻止倒计时** | `startCountdown` 仅在以下均为 false 时自动启动：`panel.sendingQueued`、`result.syncState?.paused`、`panel.manuallyPaused`、`panel.isEditing`，且 `panel.countdown === null`。任一为 true 则不会启动。 |
| **C. 轮询被跳过**     | `startPolling` 中若 `panel.sending === true` 则本次轮询直接 return，若该状态残留，会持续拿不到新 ready 消息或延迟很久。                                                                               |
| **D. 渲染/性能**      | 旧设备上 Vue 更新或 DOM 渲染慢，倒计时和输入框已更新但用户感知不到。                                                                                                                                  |

### 相关代码位置

- 前端检测 ready 并写日志：`wecom-desktop/src/views/SidecarView.vue` 约 451–491 行（`fetchQueueState`）。
- 自动启动倒计时条件：同上 497–506 行。
- 轮询跳过逻辑：同上 954–957 行（`if (panel.sending) return`）。

---

## 问题 2：发送两条相同消息（重复发送）

### 现象（日志时间线示例）

```
15:38:13  [AI] Message ready for 1871515369-[重复(保底正常)]
15:38:56  [WARNING] [FOLLOWUP] Sidecar send failed: timeout
15:38:56  [FOLLOWUP] Sending message directly (no Sidecar review)
15:39:11  [FOLLOWUP] Message sent directly
15:39:11  [FOLLOWUP] Message xxx marked as SENT (direct send)
15:39:12  [FOLLOWUP] Reply sent (via Sidecar)
```

即：先超时 → 直接发送成功 → 随后又出现 "Reply sent (via Sidecar)"，实际会话中出现两条相同内容。

### 根因：竞态条件（Race Condition）

1. **后端**在 `response_detector.py` 中调用 `sidecar_client.wait_for_send(msg_id, timeout=...)`（由 `_get_sidecar_timeout()` 或历史硬编码决定），对应后端路由 `POST /sidecar/{serial}/queue/wait/{message_id}`。实现上为事件驱动唤醒与有界轮询（非固定 100ms），超时后返回 `{"success": false, "reason": "timeout"}`。

2. **前端**在某一时刻检测到 ready，启动 10 秒倒计时，到期后调用 `sendQueuedMessage` → 请求 `POST /sidecar/{serial}/queue/send/{message_id}`。该接口会：
   - 将消息状态设为 `SENDING`；
   - 调用 `session.send_message(message_to_send)`（通过设备 UI 发送）；
   - 成功后将状态设为 `SENT`。

3. **在旧设备上**，`session.send_message()` 执行很慢（ADB/UI 操作耗时长），消息会长时间处于 `SENDING`。

4. **后端 `wait_for_send` 超时逻辑**（`wecom-desktop/backend/routers/sidecar.py` 约 1271–1280 行）：
   - 当 `elapsed >= timeout` 时，仅当 `msg.status in (PENDING, READY)` 才将消息设为 `EXPIRED`。
   - 若此时状态已是 `SENDING`，**不会**被改为 `EXPIRED`，但仍返回 `{"success": false, "reason": "timeout"}`。

5. **`response_detector.py` 对返回值的处理**（约 2479–2494 行）：
   - `reason == "sent"` → 成功，返回。
   - `reason == "cancelled"` / `reason == "expired"` → 不发送，返回。
   - **其他（包含 `reason === "timeout"`）** → 进入 `else`，打 "Sidecar send failed" 日志后**没有 return**，代码继续执行到下方的「直接发送」逻辑。

6. **结果**：
   - 第一条：前端倒计时结束 → `/queue/send/{message_id}` 已把消息发到设备（可能仍在 `SENDING` 或刚变 `SENT`）。
   - 第二条：后端因收到 `reason === "timeout"` 走直接发送分支，再调 `POST /sidecar/{serial}/send`，又发一次同内容。

因此，「超级验证」或其它防重逻辑无法避免这类重复，因为两条发送来自不同路径（队列发送 + 超时后的直接发送），且超时返回未区分「已过期」与「正在发送中」。

### 根因小结（Bug 列表）

| #     | 位置                                                     | 描述                                                                                                          |
| ----- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Bug 1 | `response_detector.py` 2488–2492 行                      | `reason === "timeout"` 未与 `"expired"` 统一处理，超时一律落入 else，必然进入直接发送。                       |
| Bug 2 | `sidecar.py` `wait_for_send` 超时分支（约 1273–1280 行） | 超时时仅对 `PENDING/READY` 标 `EXPIRED`；若为 `SENDING` 既不标 `EXPIRED` 也不等待发送结束，直接返回 timeout。 |
| Bug 3 | `response_detector.py` 2492 之后                         | else 分支未在「直接发送」前检查消息是否已在发送（`SENDING`）或已发送（`SENT`），导致重复发送。                |

### 相关代码位置

- 等待与分支逻辑：`wecom-desktop/backend/services/followup/response_detector.py` 约 2476–2534 行（`_send_via_sidecar_or_direct`）。
- 后端 wait 与超时：`wecom-desktop/backend/routers/sidecar.py` 约 1253–1320 行（`wait_for_send`）。
- 队列发送：`wecom-desktop/backend/routers/sidecar.py` 约 961–1018 行（`send_queued_message`）。

---

## 影响

- **谁受影响**：使用 FollowUp + Sidecar 且在旧设备或高延迟环境下运行的用户。
- **表现**：同一客户收到两条相同回复，体验差且可能引发误解；Sidecar 倒计时/消息不显示导致误以为未走审核流程。

---

## 建议修复方向

### 1. 超时与「正在发送」的区分（后端 `wait_for_send`）

- 在超时分支中，若 `msg.status == SENDING`，先短时轮询等待（例如最多再等 5–10 秒），若变为 `SENT` 则返回 `success=True, reason="sent"`；若仍为 `SENDING` 再按当前超时逻辑返回 timeout（并可考虑将状态标为 FAILED 或保留 SENDING 以便排查）。
- 仅对 `PENDING`/`READY` 标 `EXPIRED`，避免把「发送中」误标为过期。

### 2. 超时后是否允许直接发送（`response_detector.py`）

- 将 `reason === "timeout"` 与 `"expired"` 同等处理：**不**进入直接发送，仅记录日志并 return False（或根据产品需求单独分支：例如仅在前端从未检测到 ready 时才允许直接发送）。
- 或在进入直接发送前，先查询队列状态：若该 `msg_id` 状态为 `sending` 或 `sent`，则不再直接发送，必要时短时等待后再次检查，若已 `sent` 则返回成功。

### 3. 前端与轮询（缓解问题 1）

- 确保发送结束后正确重置 `panel.sending` / `panel.sendingQueued`，避免轮询被长期跳过。
- 可选：在设备慢时适当缩短 `pollIntervalMs` 或对「当前设备」做一次快速轮询（例如 ready 后前几轮 2–3 秒一次），以便更快展示倒计时。

---

## 相关文档与代码

- Sidecar 设计：`docs/01-product/` 下 Sidecar/FollowUp 相关说明。
- 实现：`wecom-desktop/backend/services/followup/response_detector.py`（`_send_via_sidecar_or_direct`）、`wecom-desktop/backend/routers/sidecar.py`（`wait_for_send`、`send_queued_message`）、`wecom-desktop/src/views/SidecarView.vue`（`fetchQueueState`、`startCountdown`、轮询）。
- 同类历史问题：`docs/04-bugs-and-fixes/fixed/followup_sidecar_not_working.md`。

---

## 文档变更

- 2026-02-09：初稿，问题 1/2 分析、根因与建议修复。
