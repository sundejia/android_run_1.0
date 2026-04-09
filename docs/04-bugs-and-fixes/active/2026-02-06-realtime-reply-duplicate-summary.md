# 实时回复重复发送问题 - 执行摘要

> **日期**: 2026-02-06
> **问题**: 客户在10秒倒计时期间收到重复回复
> **严重程度**: P1
> **状态**: 🔴 待修复

---

## 🎯 问题简述

**症状**: 客户会收到**两条相同的回复消息**

**原因**: 实时回复在10秒倒计时期间，下一次扫描又检测到同一条消息，导致重复生成回复

**影响**: 用户体验差，客服形象受损，资源浪费

---

## 📊 问题时间线

```
T0:   客户发送消息 "你好"
T1:   Realtime Reply 检测到 → AI生成回复M1 → 加入Sidecar → 开始10秒倒计时
T5:   下一次扫描开始 → 又检测到同一条消息 → AI生成回复M2 ❌
T10:  M1发送成功
T20:  M2发送成功 ❌
```

**问题窗口**: 10秒倒计时期间

---

## 💡 解决方案（三层防护）

### 1️⃣ 紧急修复：全局扫描锁

**实施时间**: 1-2小时
**改动范围**: 仅 `ResponseDetector` 类
**效果**: 立即阻止并发扫描

```python
class ResponseDetector:
    def __init__(self):
        self._device_scan_locks: Dict[str, asyncio.Lock] = {}

    async def detect_and_reply(self, device_serial: str, ...):
        # 🔒 获取设备锁
        device_lock = await self._get_device_lock(device_serial)

        # 如果已有扫描在进行，跳过
        if device_lock.locked():
            return {"skipped": True, "reason": "Scan in progress"}

        # 🔒 获取锁后才开始扫描
        async with device_lock:
            # ... 原有逻辑 ...
```

**优先级**: 🔴 P0 - 立即实施

---

### 2️⃣ 完整修复：消息处理状态表

**实施时间**: 4-6小时
**改动范围**: 新建表 + 仓库类 + 集成

**数据库表**:

```sql
CREATE TABLE message_processing_status (
    id INTEGER PRIMARY KEY,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    message_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- 'processing', 'sent', 'cancelled'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_serial, customer_name, message_id)
);
```

**关键方法**:

```python
# 检查消息是否正在处理
await repo.is_message_processing(device_serial, customer_name, message_id)

# 标记为处理中
await repo.mark_as_processing(...)

# 标记为已发送
await repo.mark_as_sent(...)

# 取消处理
await repo.cancel_processing(...)
```

**优先级**: 🟡 P1 - 本周完成

---

### 3️⃣ 补充防护：Sidecar队列去重

**实施时间**: 2-3小时
**效果**: 在Sidecar层面自动替换旧消息

```python
async def add_message(self, contact_name: str, message: str):
    # 检查是否有待发送消息
    existing = await self._get_pending_message(contact_name)

    if existing:
        # 取消旧消息，替换为新消息
        await self.update_status(existing['id'], CANCELLED)

    # 添加新消息
    # ...
```

**优先级**: 🟢 P2 - 有余力时实施

---

## 🚀 快速实施指南

### Step 1: 全局扫描锁（立即）

**文件**: `wecom-desktop/backend/services/followup/response_detector.py`

**改动点**:

1. 添加 `_device_scan_locks` 字典
2. 添加 `_get_device_lock()` 方法
3. 在 `detect_and_reply()` 开始处获取锁

**预期效果**:

- ✅ 立即阻止并发扫描
- ✅ 代码改动最小（< 50行）
- ✅ 无需数据库改动

---

### Step 2: 消息处理状态表（本周）

**新建文件**:

- `services/realtime/message_status_repository.py`

**修改文件**:

- `response_detector.py` - 集成状态检查
- `realtime_reply_process.py` - 传递仓库实例

**预期效果**:

- ✅ 精确防止重复处理
- ✅ 可追溯处理历史
- ✅ 支持监控和调试

---

## 📋 验证测试

### 测试场景1: 正常回复

```
1. 客户发送 "你好"
2. 等待15秒
3. 预期: 收到1条回复 ✅
```

### 测试场景2: 快速连续消息

```
1. 客户发送 "你好"
2. 5秒后发送 "在吗"
3. 预期: 收到2条不同的回复 ✅
```

### 测试场景3: 扫描重叠

```
1. 设置扫描间隔10秒
2. 客户发送消息
3. 预期: 收到1条回复 ✅
```

---

## 📈 监控指标

| 指标       | 当前值 | 目标值 |
| ---------- | ------ | ------ |
| 重复回复率 | ~5%    | < 0.1% |
| 扫描冲突   | N/A    | < 5%   |

---

## 🔗 相关文档

- **完整分析报告**: [2026-02-06-realtime-reply-duplicate-during-countdown.md](./2026-02-06-realtime-reply-duplicate-during-countdown.md)
- **Realtime Reply设计**: [../../01-product/realtime-reply-system.md](../../01-product/realtime-reply-system.md)
- **Sidecar队列**: [../../01-product/sidecar-queue-system.md](../../01-product/sidecar-queue-system.md)

---

## ⚡ 下一步行动

**立即执行** (今天):

1. 实施**全局扫描锁**
2. 测试验证
3. 部署到生产环境

**本周完成**:

1. 实施**消息处理状态表**
2. 添加监控API
3. 完整测试验证

**有时间再做**:

1. 实施**Sidecar队列去重**
2. 优化扫描间隔
3. 添加智能合并

---

**状态**: 🔴 待修复
**优先级**: P0 - 紧急
**预计修复时间**: 2小时（紧急） + 6小时（完整）
