# Sidecar 队列消息发送给错误用户分析

> **Documentation note (2026-04-15):** Seeded default for `sidecar_timeout` is now **60 s** (was 300 s). The timeline below is a **historical** incident from 2026-02-05 when the longer wait applied. See [Sidecar review timeout defaults](../../sidecar/sidecar-review-timeout-defaults.md).

## 问题描述

**问题发生时间**: 2026-02-05 19:11-19:24

**问题现象**: 本应发送给用户 `B2602050044-(保底正常)` 的消息 **"好的宝子。那等你出院后我们再详细沟通开播事宜。"** 错误地发送给了用户 `B2602040221-(保底正常)`。

**问题影响**: 客户 `B2602040221` 收到完全不相关的消息后非常生气，回复：**"你才出院 莫名其妙 你几个意思"**、**"你有病吗 你才出院"**

**严重程度**: P0 - 严重，导致客户流失和品牌形象损害

---

## 完整时间线

### 阶段 1: 处理 B2602050044 (正确流程)

| 时间     | 事件                              | 说明                                             |
| -------- | --------------------------------- | ------------------------------------------------ |
| 19:11:05 | 开始处理 `B2602050044-(保底正常)` | 客户说"我在医院过几天出院了播"                   |
| 19:11:23 | AI 生成回复                       | "好的宝子。那等你出院后我们再详细沟通开播事宜。" |
| 19:11:23 | 消息加入 Sidecar 队列             | `msg_id: 4cad13b5-cb4f-4a96-81b7-6f9688bbe116`   |
| 19:11:23 | 开始 5 分钟倒计时                 | 等待用户在 Sidecar UI 审核/发送                  |
| 19:16:23 | **Sidecar 超时**                  | 5 分钟内无操作，`reason: timeout`                |
| 19:16:23 | 回退到直接发送                    | `📤 Sending message directly`                    |
| 19:16:33 | 消息发送成功                      | 验证显示消息确实在 B2602050044 的聊天窗口中      |
| 19:16:46 | 返回消息列表                      | ✅ 第一个用户处理完成                            |

### 阶段 2: 处理 B2602040221 (问题发生)

| 时间         | 事件                              | 说明                                              |
| ------------ | --------------------------------- | ------------------------------------------------- |
| 19:16:48     | 开始处理 `B2602040221-(保底正常)` | 客户消息: "没"                                    |
| 19:16:59     | 进入 B2602040221 聊天窗口         | 屏幕已切换到新用户                                |
| 19:17:05     | AI 生成回复                       | "好的宝子，那我们先加个联系方式，方便后续沟通。"  |
| 19:17:05     | 消息加入 Sidecar 队列             | `msg_id: 96868d50-f16b-4482-9635-654c111b7feb`    |
| 19:17:05     | 开始 5 分钟倒计时                 | ⚠️ **此时队列中有两条 READY 状态的消息！**        |
| 19:22:05     | Sidecar 超时                      | 第二条消息也超时                                  |
| 19:22:15     | 直接发送                          | 发送第二条消息                                    |
| **19:22:19** | **发现问题**                      | 在 B2602040221 聊天窗口中检测到**两条**客服消息！ |

### 阶段 3: 问题显现

```log
19:22:19 | [5] [KEFU] text: 好的宝子。那等你出院后我们再详细沟通开播事宜。  ← 错误消息！
19:22:19 | [6] [KEFU] text: 好的宝子，那我们先加个联系方式，方便后续沟通。  ← 正确消息
```

### 阶段 4: 客户反应

```log
19:24:12 | User: B2602040221-(保底正常) | Preview: '你才出院 莫名其妙 你几个意思' | Unread: 4
19:24:29 | CUSTOMER stored: 出院？
19:24:29 | CUSTOMER stored: 你有病吗 你才出院
```

---

## 根因分析

### 根因 1: Sidecar 超时后队列消息状态未更新 (Critical)

**问题代码位置**: `wecom-desktop/backend/routers/sidecar.py` 第 1200-1204 行

```python
# wait_for_send 函数
while True:
    elapsed = time.time() - start_time
    if elapsed >= timeout:
        return {"success": False, "reason": "timeout"}  # ⚠️ 只返回结果，未更新队列中的消息状态！
```

**问题**: 当 `wait_for_send` 因超时返回时，队列中的消息**仍然保持 READY 状态**，没有被标记为 SENT、FAILED 或 CANCELLED。

**后果**:

- 第一条消息 (`4cad13b5-...`) 即使通过直接发送成功，队列中的记录仍为 READY
- 当处理第二个用户时，队列中积累了多条 READY 状态的消息
- Sidecar UI 会显示所有 READY 状态的消息，导致混淆

### 根因 2: send_message 不验证当前聊天窗口 (Critical)

**问题代码位置**: `src/wecom_automation/services/wecom_service.py` 第 2108-2186 行

```python
async def send_message(self, text: str) -> tuple[bool, str]:
    """Send a text message in the current conversation."""
    # ⚠️ 没有验证当前聊天窗口是否是目标用户！
    # 直接在当前屏幕发送消息
    ui_tree, elements = await self.adb.get_ui_state()
    input_field = self._find_input_field(elements)
    await self.adb.input_text(text)
    send_button = self._find_send_button(elements)
    await self._tap_element(send_button)
    return True, text
```

**问题**: `send_message` 只是在当前屏幕上发送消息，完全不验证聊天对象是否正确。

**后果**: 如果用户在 Sidecar UI 点击发送队列中的旧消息，消息会发送到**当前打开的聊天窗口**，而不是消息原本对应的联系人。

### 根因 3: 队列消息与当前屏幕状态不同步

**问题**: Sidecar 队列设计时假设消息会按顺序处理，且在发送时屏幕状态与消息创建时一致。

**实际情况**:

1. 消息 A 为用户 A 创建，加入队列
2. Sidecar 超时，直接发送（成功）
3. 自动化流程继续，进入用户 B 的聊天
4. 消息 B 为用户 B 创建，加入队列
5. **此时队列中有两条消息，但屏幕只显示用户 B 的聊天！**
6. 如果用户点击发送消息 A，消息 A 会发送到用户 B

---

## 问题触发条件

1. **Sidecar 超时发生** - 5 分钟内用户未在 Sidecar UI 审核消息
2. **直接发送成功后继续处理下一个用户** - 自动化流程不会等待
3. **队列中残留旧消息** - 超时后消息状态未更新
4. **用户/系统在错误时机发送旧消息** - 屏幕已切换到其他用户

---

## 问题流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    处理 B2602050044                              │
├─────────────────────────────────────────────────────────────────┤
│ 1. 生成消息 A: "好的宝子。那等你出院后..."                        │
│ 2. 加入队列 (msg_id: 4cad13b5, 状态: READY)                      │
│ 3. 等待 5 分钟...                                                │
│ 4. 超时! wait_for_send 返回 {reason: timeout}                   │
│    ⚠️ 队列中的消息仍为 READY 状态!                               │
│ 5. 回退到直接发送 → 成功                                         │
│ 6. 返回列表                                                      │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    处理 B2602040221                              │
├─────────────────────────────────────────────────────────────────┤
│ 1. 进入 B2602040221 聊天窗口                                     │
│ 2. 生成消息 B: "好的宝子，那我们先加个联系方式..."                 │
│ 3. 加入队列 (msg_id: 96868d50, 状态: READY)                      │
│                                                                  │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │         Sidecar 队列此时的状态:                               ││
│ │                                                               ││
│ │  [0] msg_id: 4cad13b5, 联系人: B2602050044, 状态: READY       ││
│ │      消息: "好的宝子。那等你出院后..."                         ││
│ │  [1] msg_id: 96868d50, 联系人: B2602040221, 状态: READY       ││
│ │      消息: "好的宝子，那我们先加个联系方式..."                  ││
│ │                                                               ││
│ │  ⚠️ 当前屏幕: B2602040221 的聊天窗口!                         ││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│ 4. 如果用户点击发送 [0] 的消息:                                   │
│    → send_message("好的宝子。那等你出院后...")                    │
│    → 消息发送到当前屏幕 (B2602040221) ← ❌ 错误发送!             │
│                                                                  │
│ 5. 超时后直接发送 [1] 的消息:                                     │
│    → send_message("好的宝子，那我们先加个联系方式...")            │
│    → 消息发送到 B2602040221 ← ✓ 正确发送                         │
│                                                                  │
│ 结果: B2602040221 收到了两条消息，其中一条是发给别人的!           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 日志证据

### 证据 1: 队列消息 ID 不同，说明是两次独立的消息创建

```log
# 第一条消息 (B2602050044)
19:11:23 | 📡 Routing message to Sidecar queue for B2602050044-(保底正常)
19:11:23 | ✅ Message queued (ID: 4cad13b5-cb4f-4a96-81b7-6f9688bbe116)

# 第二条消息 (B2602040221)
19:17:05 | 📡 Routing message to Sidecar queue for B2602040221-(保底正常)
19:17:05 | ✅ Message queued (ID: 96868d50-f16b-4482-9635-654c111b7feb)
```

### 证据 2: Sidecar 超时但未清理队列

```log
19:16:23 | WARNING  | Sidecar send failed: timeout
19:16:23 | INFO     | 📤 Sending message directly (no Sidecar review)
# ⚠️ 没有日志显示队列中的消息被清理或状态被更新
```

### 证据 3: 两条消息同时出现在 B2602040221 的聊天窗口

```log
19:22:19 | [5] [KEFU] text: 好的宝子。那等你出院后我们再详细沟通开播事宜。  ← 错误!
19:22:19 | [6] [KEFU] text: 好的宝子，那我们先加个联系方式，方便后续沟通。  ← 正确
```

### 证据 4: 消息被存储到 B2602040221 的数据库记录

```log
19:24:29 | 📊 Processing 7 messages for B2602040221-(保底正常)...
19:24:29 | [1/7] ✅ 👤 KEFU stored: 好的宝子。那等你出院后我们再详细沟通开播事宜。... (db_id=4236)
```

---

## 修复方案

### 修复 1: Sidecar 超时后清理队列消息 (P0)

**位置**: `wecom-desktop/backend/routers/sidecar.py`

```python
# wait_for_send 函数修改
async def wait_for_send(serial: str, message_id: str, timeout: float = 60.0):
    while True:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            # ✅ 超时后标记消息为 EXPIRED
            queue = _get_queue(serial)
            msg = next((m for m in queue if m.id == message_id), None)
            if msg and msg.status in (MessageStatus.PENDING, MessageStatus.READY):
                msg.status = MessageStatus.EXPIRED  # 新增状态
                logger.info(f"Message {message_id} marked as EXPIRED due to timeout")
            return {"success": False, "reason": "timeout"}
        # ... rest of the code
```

### 修复 2: 直接发送成功后清理队列消息 (P0)

**位置**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

```python
# _send_and_save_message 函数修改
async def _send_and_save_message(...):
    # ... existing Sidecar queue logic ...

    if reason == "timeout":
        # ✅ 直接发送成功后，标记队列中的消息
        if sidecar_client and msg_id:
            await sidecar_client.mark_as_sent(msg_id)  # 新增方法

    # 直接发送
    success = await session.send_message(message)
    if success:
        return True, message
```

### 修复 3: send_message 添加联系人验证 (P0)

**位置**: `src/wecom_automation/services/wecom_service.py`

```python
async def send_message(self, text: str, expected_contact: str | None = None) -> tuple[bool, str]:
    """Send a text message in the current conversation."""

    # ✅ 验证当前聊天窗口是否正确
    if expected_contact:
        current_contact = await self._get_current_chat_contact()
        if current_contact and not self._contact_matches(current_contact, expected_contact):
            self.logger.error(
                f"Contact mismatch! Expected: {expected_contact}, Current: {current_contact}"
            )
            return False, text  # 拒绝发送

    # ... existing send logic ...
```

### 修复 4: 队列消息添加联系人绑定验证 (P1)

**位置**: `wecom-desktop/backend/routers/sidecar.py`

```python
@router.post("/{serial}/queue/send/{message_id}")
async def send_queued_message(serial: str, message_id: str, ...):
    msg = next((m for m in queue if m.id == message_id), None)

    # ✅ 验证当前聊天窗口是否是消息对应的联系人
    session = get_session(serial)
    current_state = await session.snapshot()

    if current_state.conversation:
        current_contact = current_state.conversation.contact_name
        if current_contact != msg.customerName:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot send: current contact ({current_contact}) != message contact ({msg.customerName})"
            )

    # ... existing send logic ...
```

### 修复 5: 切换用户时清理过期队列消息 (P1)

**位置**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

```python
async def _process_user(self, ...):
    # ✅ 在开始处理新用户前，清理队列中不属于该用户的消息
    if sidecar_client:
        await sidecar_client.clear_expired_messages()
        await sidecar_client.cancel_messages_for_other_contacts(current_user_name)

    # ... existing processing logic ...
```

---

## 临时规避措施

在修复完成前，可采取以下临时措施：

1. **禁用 Sidecar 审核功能**
   - 设置 `send_via_sidecar: false`
   - 直接发送消息，避免队列积累

2. **减少 Sidecar 超时时间**
   - 将 300 秒改为 30 秒
   - 减少队列消息残留的窗口期

3. **增加操作人员培训**
   - 警告不要在 Sidecar UI 点击发送旧消息
   - 确认消息联系人与当前屏幕一致

---

## 相关代码文件

| 文件                                                                   | 功能             | 修复项                             |
| ---------------------------------------------------------------------- | ---------------- | ---------------------------------- |
| `wecom-desktop/backend/routers/sidecar.py`                             | Sidecar 队列 API | wait_for_send, send_queued_message |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 实时回复检测器   | \_send_and_save_message            |
| `src/wecom_automation/services/wecom_service.py`                       | 消息发送         | send_message                       |
| `src/wecom_automation/services/integration/sidecar.py`                 | Sidecar 客户端   | wait_for_send, add_message         |

---

## 后续跟进

- [x] 实现修复 1: Sidecar 超时后标记消息为 EXPIRED (P0, 2026-02-05 已完成)
- [x] 实现修复 2: 直接发送成功后清理队列消息 (P0, 2026-02-05 已完成)
- [x] 实现修复 5: 切换用户时清理过期队列消息 (P1, 2026-02-05 已完成)
- [ ] 实现修复 3: send_message 添加联系人验证 (P2, 可选)
- [ ] 实现修复 4: 队列消息添加联系人绑定验证 (P2, 可选)
- [ ] 添加监控告警：检测消息发送给错误联系人的情况
- [ ] 编写单元测试覆盖边界场景
- [ ] 更新 Sidecar UI，显示消息对应的联系人信息

---

## 修复记录

### 2026-02-05 修复内容

**修复 1: MessageStatus 添加 EXPIRED 状态**

- 文件: `wecom-desktop/backend/routers/sidecar.py`
- 在 MessageStatus 枚举中添加 `EXPIRED = "expired"`
- 在 `wait_for_send` 超时时标记消息为 EXPIRED

**修复 2: 直接发送成功后标记队列消息**

- 文件: `wecom-desktop/backend/routers/sidecar.py`
  - 新增 API: `POST /{serial}/queue/mark-sent/{message_id}`
  - 新增 API: `POST /{serial}/queue/clear-expired`
- 文件: `src/wecom_automation/services/integration/sidecar.py`
  - 新增方法: `mark_as_sent_directly(message_id)`
  - 新增方法: `clear_expired_messages()`
- 文件: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`
  - 在 `_send_and_save_message` 直接发送成功后调用 `mark_as_sent_directly`

**修复 3: 切换用户时清理过期消息**

- 文件: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`
- 在 `_process_unread_user_with_wait` 开始处理新用户前调用 `clear_expired_messages`

---

## 版本信息

- **问题发现日期**: 2026-02-05
- **分析完成日期**: 2026-02-05
- **修复完成日期**: 2026-02-05
- **日志文件**: `scanner(2).log` 第 16900-17500 行
- **修复状态**: P0/P1 已修复
- **优先级**: P0 (最高)

---

_文档创建者: AI Assistant_  
_最后更新: 2026-02-05_
