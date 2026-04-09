# 补刀机制说明 - 触发条件与故障排查

> **更新日期**: 2026-02-06
> **功能**: 企业微信自动补刀（Follow-up）

---

## 📋 补刀功能概述

### 什么是补刀？

**补刀**（Follow-up）是指当客服（Kefu）发送消息后，如果客户在一段时间内没有回复，系统自动发送补刀消息来重新 engagement 客户。

### 应用场景

- 客服发送产品介绍后，客户未回复 → 30分钟后自动发送："有什么问题可以随时问我"
- 客服发送报价后，客户未回复 → 1小时后自动发送其他优惠信息
- 客服发送问候后，客户未回复 → 2小时后再次问候

---

## 🎯 补刀触发条件

### 必需条件（全部满足才能触发）

#### 1️⃣ 补刀功能已启用

**配置路径**: 前端设置 → Followup → `followup_enabled`

**检查方法**:

```python
# 在 queue_manager.py:132-134
def is_enabled(self) -> bool:
    """检查补刀功能是否启用"""
    return self._get_settings().followup_enabled
```

**默认值**: `False`（必须手动启用）

#### 2️⃣ 最后一条消息是客服发送的

**判断逻辑**: `last_message_sender == "kefu"`

**代码位置**: `queue_manager.py:221`

```python
elif conv.last_message_sender == "kefu":
    # Kefu 发的消息，检查是否超过阈值
    if conv.last_message_time:
        time_since = now - last_msg_time
        if time_since >= idle_threshold:
            # 可以触发补刀
```

**为什么**: 只有客服最后发消息，客户没有回复，才需要补刀。如果客户刚发了消息，不需要补刀。

#### 3️⃣ 客服发送最后一条消息后，经过的时间超过空闲阈值

**配置**: `idle_threshold_minutes`（默认：30分钟）

**代码位置**: `queue_manager.py:234`

```python
idle_threshold = timedelta(minutes=settings.idle_threshold_minutes)
# ...
if time_since >= idle_threshold:
    # 加入补刀队列
```

**计算方式**:

```
当前时间 - 最后消息时间 >= 空闲阈值（30分钟）
```

**示例**:

- 客服 14:00 发送消息
- 当前时间 14:35
- 空闲时长 = 35分钟 > 30分钟阈值 → **可以触发补刀** ✅

#### 4️⃣ 当前在工作时间内（如果启用了工作时间限制）

**配置**: `enable_operating_hours` + `start_hour` + `end_hour`

**代码位置**: `queue_manager.py:147-149`

```python
if settings.enable_operating_hours:
    if not self.is_within_operating_hours():
        return False, "Outside operating hours"
```

**默认工作时间**: 09:00 - 18:00

#### 5️⃣ 客户不在黑名单中

**检查位置**: `queue_manager.py:256-267`

```python
if BlacklistChecker.is_blacklisted(
    self.device_serial,
    conv.customer_name,
    conv.customer_channel,
):
    self._log("⛔ 黑名单用户，跳过入队")
    continue  # 不触发补刀
```

#### 6️⃣ 补刀次数未达到上限

**配置**: `max_attempts_per_customer`（默认：3次）

**代码位置**: `attempts_repository.py` 和 `executor.py`

```python
# 检查当前尝试次数
if current_attempt >= max_attempts:
    # 标记为已完成，不再补刀
    status = AttemptStatus.COMPLETED
```

---

## 🔄 补刀执行流程

### 完整流程图

```
1. 实时回复扫描结束
   ↓
2. 调用 FollowupQueueManager.process_conversations()
   ↓
3. 遍历所有对话
   ↓
4. 对每个对话检查：
   ├─ 最后消息发送方是谁？
   │  ├─ 客户 → 移出补刀队列（客户已回复）
   │  └─ 客服 → 继续检查
   │      ├─ 空闲时间 >= 阈值？
   │      │  ├─ 是 → 加入补刀队列
   │      │  └─ 否 → 跳过
   ├─ 在黑名单？ → 跳过
   └─ 已达到补刀上限？ → 跳过
   ↓
5. 执行补刀（如果没有实时回复红点）
   ↓
6. 对队列中的每个客户发送补刀消息
   ↓
7. 记录补刀尝试次数
```

### 关键代码位置

| 功能         | 文件               | 方法/行号                         |
| ------------ | ------------------ | --------------------------------- |
| 队列管理     | `queue_manager.py` | `process_conversations()` (155行) |
| 触发条件检查 | `queue_manager.py` | `can_execute()` (140行)           |
| 执行补刀     | `executor.py`      | `execute_batch()` (900行)         |
| 消息生成     | `queue_manager.py` | `_generate_message()` (526行)     |

---

## ⚠️ 为什么补刀触发不了？

### 常见原因排查

#### 1️⃣ 补刀功能未启用 ⭐ 最常见

**症状**: 日志显示 "补刀功能未启用，跳过处理"

**检查**:

```bash
# 查看数据库设置（与主业务库同文件）
sqlite3 wecom_conversations.db "SELECT key, value_bool FROM settings WHERE category='followup' AND key='followup_enabled'"
```

**解决**: 在前端设置中启用补刀功能

---

#### 2️⃣ 客户刚刚回复了

**症状**: 日志显示 "客户已回复，移出补刀队列"

**原因**: 补刀只对"客服发消息后客户不回复"的场景有效。如果客户刚回复，不会触发补刀。

**示例**:

```
14:00 客服: "你好，有什么可以帮您的？"
14:05 客户: "我想咨询产品"  ← 客户回复了
14:35 补刀检查 → 不会触发 ❌（客户刚回复）
```

---

#### 3️⃣ 空闲时间未达到阈值

**症状**: 日志显示 "未达到空闲阈值 (15 < 30分钟)"

**默认阈值**: 30分钟

**示例**:

```
14:00 客服: "你好"
14:15 补刀检查 → 15分钟 < 30分钟 → 不触发 ❌
14:35 补刀检查 → 35分钟 > 30分钟 → 触发 ✅
```

**解决**:

- 等待更长时间
- 或调整 `idle_threshold_minutes` 设置（最小值：5分钟）

---

#### 4️⃣ 不在工作时间内

**症状**: 日志显示 "Outside operating hours (09:00 - 18:00)"

**默认工作时间**: 09:00 - 18:00

**检查**: 当前时间是否在 09:00-18:00 之外

**解决**:

- 在工作时间内测试
- 或调整工作时间设置
- 或禁用工作时间限制 (`enable_operating_hours = False`)

---

#### 5️⃣ 已经达到补刀次数上限

**症状**: 日志显示 "已达到最大补刀次数 (3次)"

**默认上限**: 3次

**检查**:

```bash
sqlite3 wecom_conversations.db "
SELECT customer_name, current_attempt, max_attempts, status
FROM followup_attempts
WHERE device_serial='YOUR_DEVICE_SERIAL'
"
```

**解决**:

- 清零补刀计数
- 或调整 `max_attempts_per_customer` 设置

---

#### 6️⃣ 客户在黑名单中

**症状**: 日志显示 "黑名单用户，跳过入队"

**检查黑名单**:

```bash
sqlite3 wecom_conversations.db "
SELECT name, channel, reason
FROM blacklist
WHERE device_serial='YOUR_DEVICE_SERIAL'
"
```

**解决**: 从黑名单中移除该客户

---

#### 7️⃣ 消息ID变化（对话继续中）

**症状**: 日志显示 "对话继续中（消息ID变化），跳过"

**原因**:

- 客服发送消息A → 进入补刀队列
- 客户回复 → 移出队列
- 客服又发送消息B → 不会立即重新入队（防止误判）

**代码逻辑**: `queue_manager.py:238-247`

---

## 🛠️ 补刀配置参数

### 完整参数列表

| 参数                        | 类型      | 默认值                | 说明                        |
| --------------------------- | --------- | --------------------- | --------------------------- |
| `followup_enabled`          | bool      | `false`               | ⭐ **是否启用补刀**         |
| `idle_threshold_minutes`    | int       | `30`                  | 空闲多少分钟后触发补刀      |
| `max_followups`             | int       | `5`                   | 每次扫描最大补刀数量        |
| `max_attempts_per_customer` | int       | `3`                   | 每个客户最大补刀次数        |
| `attempt_intervals`         | list[int] | `[60, 120, 180]`      | 第1/2/3次补刀的间隔（分钟） |
| `use_ai_reply`              | bool      | `false`               | 是否使用AI生成补刀消息      |
| `message_templates`         | list[str] | `["Hello...", "..."]` | 补刀消息模板（不使用AI时）  |
| `followup_prompt`           | str       | `""`                  | AI补刀提示词                |
| `enable_operating_hours`    | bool      | `false`               | 是否启用工作时间限制        |
| `start_hour`                | str       | `"09:00"`             | 工作开始时间                |
| `end_hour`                  | str       | `"18:00"`             | 工作结束时间                |
| `avoid_duplicate_messages`  | bool      | `false`               | 是否避免重复消息            |

### 如何修改配置

**方法1**: 通过前端界面

1. 打开 Electron 应用
2. 进入设置页面
3. 找到 "Followup" 分类
4. 修改参数并保存

**方法2**: 直接修改数据库

```sql
-- 启用补刀
UPDATE settings SET value='true' WHERE key='followup_enabled';

-- 设置空闲阈值为15分钟
UPDATE settings SET value='15' WHERE key='idle_threshold_minutes';

-- 设置最大补刀次数为5次
UPDATE settings SET value='5' WHERE key='max_attempts_per_customer';
```

---

## 📊 补刀日志示例

### 正常触发补刀

```
[QueueMgr] ┌────────────────────────────────────────────────┐
[QueueMgr] │ 补刀队列: 处理对话列表                            │
[QueueMgr] └────────────────────────────────────────────────┘
[QueueMgr]   输入对话数: 5
[QueueMgr]   补刀配置:
[QueueMgr]     - 空闲阈值: 30 分钟
[QueueMgr]     - 最大补刀次数: 3
[QueueMgr]     - 当前时间: 14:35:20

[QueueMgr]   处理每个对话:
[QueueMgr]     [1/5] 张三
[QueueMgr]       - 最后消息发送方: kefu
[QueueMgr]       - 最后消息时间: 2026-02-06 14:00:15
[QueueMgr]       - 队列状态: 无
[QueueMgr]       - 空闲时长: 35 分钟
[QueueMgr]       - 超过阈值 (30分钟)
[QueueMgr]       ✅ 加入补刀队列 (空闲 35 分钟)

[QueueMgr]   ┌────────────────────────────────────────────────┐
[QueueMgr]   │ 处理结果统计                                    │
[QueueMgr]   ├────────────────────────────────────────────────┤
[QueueMgr]   │  新增入队: 1                                  │
[QueueMgr]   │  移出队列: 0                                  │
[QueueMgr]   └────────────────────────────────────────────────┘
```

### 未触发补刀（各种原因）

```
[QueueMgr]   [2/5] 李四
[QueueMgr]     - 最后消息发送方: customer
[QueueMgr]     - 队列状态: pending
[QueueMgr]     ✅ 客户已回复，移出补刀队列

[QueueMgr]   [3/5] 王五
[QueueMgr]     - 最后消息发送方: kefu
[QueueMgr]     - 最后消息时间: 2026-02-06 14:25:00
[QueueMgr]     - 空闲时长: 10 分钟
[QueueMgr]     ⏭️ 未达到空闲阈值 (10 < 30分钟)

[QueueMgr]   [4/5] 赵六
[QueueMgr]     - 最后消息发送方: kefu
[QueueMgr]     - 最后消息时间: 2026-02-06 14:00:00
[QueueMgr]     - 队列状态: pending
[QueueMgr]     ⏭️ 已在待处理队列中，保持不变

[QueueMgr]   [5/5] 孙七
[QueueMgr]     - 最后消息发送方: kefu
[QueueMgr]     - 空闲时长: 45 分钟
[QueueMgr]     ⛔ 黑名单用户，跳过入队
```

---

## 🔍 调试补刀问题

### Step 1: 检查补刀是否启用

```python
# 查看设置
from services.settings import get_settings_service
svc = get_settings_service()
settings = svc.get_followup_settings()
print(f"followup_enabled = {settings.followup_enabled}")
```

### Step 2: 查看补刀队列状态

```bash
sqlite3 wecom_conversations.db "
SELECT
    customer_name,
    current_attempt,
    max_attempts,
    status,
    last_followup_at
FROM followup_attempts
WHERE device_serial='YOUR_DEVICE_SERIAL'
ORDER BY created_at DESC
LIMIT 10
"
```

### Step 3: 查看最后消息信息

```bash
sqlite3 wecom_conversations.db "
SELECT
    m.sender,
    m.timestamp,
    m.content,
    c.name as customer_name
FROM messages m
JOIN customers c ON m.customer_id = c.id
WHERE c.device_serial = 'YOUR_DEVICE_SERIAL'
ORDER BY m.timestamp DESC
LIMIT 5
"
```

### Step 4: 检查工作时间

```python
from datetime import datetime
from services.followup.settings import SettingsManager

mgr = SettingsManager()
print(f"当前在工作时间内: {mgr.is_within_operating_hours()}")
print(f"当前时间: {datetime.now().strftime('%H:%M:%S')}")
```

### Step 5: 查看详细日志

```bash
# 查看补刀相关日志
tail -f logs/*followup*.log | grep -E "QueueMgr|补刀"
```

---

## 🎯 快速验证补刀功能

### 测试步骤

1. **启用补刀功能**

   ```sql
   UPDATE settings SET value='true' WHERE key='followup_enabled';
   ```

2. **设置较短的空闲阈值（用于测试）**

   ```sql
   UPDATE settings SET value='5' WHERE key='idle_threshold_minutes';
   ```

3. **禁用工作时间限制**

   ```sql
   UPDATE settings SET value='false' WHERE key='enable_operating_hours';
   ```

4. **确保客户不在黑名单**

   ```sql
   DELETE FROM blacklist WHERE name='测试客户';
   ```

5. **触发场景**:
   - 客服发送消息给客户
   - 等待5分钟
   - 运行实时回复扫描（如果没有红点用户）

6. **检查日志**:
   ```
   [QueueMgr] ✅ 加入补刀队列 (空闲 5 分钟)
   [Executor] 开始执行补刀
   [Executor] 发送补刀消息: "Hello, have you considered our offer?"
   ```

---

## 📚 相关文档

- [补刀系统架构](../../03-impl-and-arch/key-modules/followup-system-design.md)
- [补刀队列管理](../../03-impl-and-arch/key-modules/followup-queue-manager.md)
- [补刀执行器](../../03-impl-and-arch/key-modules/followup-executor.md)
- [补刀设置说明](../../01-product/followup-settings-guide.md)

---

## ❓ 常见问题

### Q1: 为什么我启用了补刀，但还是没有触发？

**A**: 请按顺序检查：

1. ⭐ `followup_enabled` 是否为 `true`
2. 最后一条消息是否是客服发送的
3. 空闲时间是否 >= 30分钟（或你设置的阈值）
4. 是否在工作时间内（如果启用了限制）
5. 客户是否在黑名单中
6. 是否已经达到补刀次数上限

### Q2: 补刀消息从哪里来？

**A**: 两种来源：

1. **AI生成** (`use_ai_reply=true`): 使用 `followup_prompt` 提示词生成
2. **模板库** (`use_ai_reply=false`): 从 `message_templates` 中随机选择

### Q3: 补刀和实时回复有什么区别？

**A**:

- **实时回复**: 客户发消息后立即回复（秒级响应）
- **补刀**: 客服发消息后客户不回复，过一段时间后主动联系（分钟/小时级）

### Q4: 如何完全禁用补刀？

**A**:

```sql
UPDATE settings SET value='false' WHERE key='followup_enabled';
```

---

**最后更新**: 2026-02-06
**维护者**: WeCom Automation Team
