# Bug 分析：编辑后的消息未正确存入数据库

> 时间: 2026-01-18  
> 状态: ✅ 已修复

---

## 问题描述

当用户在 Sidecar 界面修改了 AI 生成的消息内容后发送，存入数据库的是**原始消息**而不是**编辑后的消息**。

---

## 根因分析

### 问题流程

```
1. AI 生成消息 "原始内容"
2. 消息添加到 Sidecar 队列
3. 用户在 Sidecar 编辑为 "修改后内容"
4. 用户点击发送
5. 后端发送 "修改后内容" ← 正确
6. wait_for_send 只返回 {success: true, reason: "sent"} ← 没有返回编辑后的消息
7. customer_syncer 使用原始 final_message 存入数据库 ← BUG！
```

### 问题代码

**位置 1**: `wecom-desktop/backend/routers/sidecar.py:1045-1046`

```python
# wait_for_send 返回值不包含编辑后的消息
if msg.status == MessageStatus.SENT:
    return {"success": True, "reason": "sent"}  # 缺少 message 字段
```

**位置 2**: `wecom-desktop/backend/routers/sidecar.py:869-884`

```python
# send_queued_message 发送编辑后消息，但未更新 msg.message
message_to_send = request.edited_message if request and request.edited_message else msg.message
# ... 发送成功后
msg.status = MessageStatus.SENT  # msg.message 仍然是原始值！
```

**位置 3**: `src/wecom_automation/services/sync/customer_syncer.py:493-499`

```python
# _send_via_sidecar 完成后
success = await self._send_via_sidecar(final_message, context)  # final_message 是原始消息
# ...
if success:
    await self._store_sent_message(final_message, context)  # 存储的是原始消息！
```

---

## 解决方案

### 方案 A: 后端返回实际发送的消息（推荐）

**修改 1**: `sidecar.py:send_queued_message` - 更新消息对象

```python
# 发送成功后更新 msg.message 为实际发送的内容
if success:
    msg.status = MessageStatus.SENT
    if request and request.edited_message:
        msg.message = request.edited_message  # 保存编辑后的内容
    sync_state.processedMessages += 1
```

**修改 2**: `sidecar.py:wait_for_send` - 返回消息内容

```python
if msg.status == MessageStatus.SENT:
    return {
        "success": True,
        "reason": "sent",
        "message": msg.message  # 返回实际发送的消息
    }
```

**修改 3**: `customer_syncer.py:_send_via_sidecar` - 使用返回的消息

```python
result = await self._sidecar_client.wait_for_send(msg_id, timeout=60.0)

reason = result.get("reason", "unknown")
if result.get("success") or reason == "sent":
    # 使用实际发送的消息（可能被用户编辑过）
    actual_message = result.get("message", message)
    self._logger.info("✅ Message sent via sidecar")
    return True, actual_message  # 返回元组
```

**修改 4**: `customer_syncer.py:_send_reply_to_customer` - 使用实际消息存储

```python
success = False
sent_message = final_message  # 默认值

if self._sidecar_client:
    success, sent_message = await self._send_via_sidecar(final_message, context)
elif hasattr(self._wecom, 'send_message'):
    success, _ = await self._wecom.send_message(final_message)

# 使用实际发送的消息存入数据库
if success:
    await self._store_sent_message(sent_message, context)
```

---

## 影响范围

| 场景                | 是否受影响                    |
| ------------------- | ----------------------------- |
| 全量同步 + Sidecar  | ✅ 受影响                     |
| 全量同步 + 直接发送 | ❌ 不受影响                   |
| 补刀系统            | ❌ 不受影响（不经过 Sidecar） |

---

## 修复文件清单

1. `wecom-desktop/backend/routers/sidecar.py`
   - `send_queued_message`: 更新 `msg.message`
   - `wait_for_send`: 返回 `message` 字段

2. `src/wecom_automation/services/sync/customer_syncer.py`
   - `_send_via_sidecar`: 返回实际消息
   - `_send_reply_to_customer`: 使用返回的消息

3. `src/wecom_automation/services/integration/sidecar.py`
   - `wait_for_send`: 返回 `message` 字段（可选，主要改后端）
