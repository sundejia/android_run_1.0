# Phase 2 候选客户查询逻辑分析

## 概述

本文档分析 Phase 2 当前的候选客户判定逻辑，以及存在的问题。

---

## 当前实现流程

### 1. 调度器层 (scheduler.py)

```python
# Phase 2: 从数据库查找候选客户
all_candidates = self._repository.find_candidates()

# 过滤条件：
# 1. is_ready = True（满足时间延迟）
# 2. 不在 Phase 1 排除列表中
ready_candidates = [
    c for c in all_candidates
    if c.is_ready and c.customer_name not in exclude_users
]

# 执行扫描，只处理 target_users 中的用户
result = await self._scanner.scan_all_devices(
    exclude_users=exclude_users,
    target_users=[c.customer_name for c in ready_candidates]
)
```

### 2. 数据库查询层 (repository.py - find_candidates)

```sql
WITH LastMessages AS (
    SELECT
        customer_id,
        MAX(CASE WHEN is_from_kefu = 1 THEN timestamp_parsed END) as last_kefu_time,
        MAX(CASE WHEN is_from_kefu = 0 THEN timestamp_parsed END) as last_customer_time,
        MAX(timestamp_parsed) as last_message_time
    FROM messages
    WHERE timestamp_parsed IS NOT NULL
    GROUP BY customer_id
)
SELECT
    c.id as customer_id,
    c.name as customer_name,
    c.channel,
    c.kefu_id,
    lm.last_kefu_time,
    lm.last_customer_time,
    lm.last_message_time
FROM customers c
JOIN LastMessages lm ON c.id = lm.customer_id
WHERE lm.last_kefu_time IS NOT NULL
  AND (lm.last_customer_time IS NULL OR lm.last_kefu_time > lm.last_customer_time)
```

**查询条件**：

- `last_kefu_time IS NOT NULL` - 客服发过消息
- `last_kefu_time > last_customer_time` - 客服最后发消息时间 > 客户最后发消息时间

### 3. Python 层过滤 (repository.py)

```python
for row in initial_rows:
    # 1. 计算已发送的跟进次数（在 last_kefu_time 之后且未回复的）
    cursor.execute("""
        SELECT COUNT(*) FROM followup_attempts
        WHERE customer_id = ?
          AND created_at > ?
          AND responded = 0
    """, (customer_id, last_kefu_time.isoformat()))
    previous_attempts = cursor.fetchone()[0]

    # 2. 检查是否达到最大次数
    if previous_attempts >= settings.max_followups:
        continue

    # 3. 计算所需延迟时间
    next_attempt_number = previous_attempts + 1
    required_delay = self._settings_manager.calculate_required_delay(next_attempt_number)

    # 4. 计算距离上次客服消息的时间
    seconds_elapsed = int((now - last_kefu_time).total_seconds())

    # 5. 判断是否满足时间条件
    is_ready = seconds_elapsed >= required_delay
```

### 4. 扫描器层 (scanner.py - scan_device)

```python
# Step 6: 检测首页红点用户
initial_unread = await self._detect_first_page_unread(wecom, serial)

# 过滤：
# 1. 排除 exclude_users（Phase 1 处理过的）
# 2. 只保留 target_users（数据库候选人）
def filter_users(users):
    result = users
    if exclude_users:
        result = [u for u in result if u.name not in exclude_users]
    if target_users is not None:
        result = [u for u in result if u.name in target_users]
    return result

initial_unread = filter_users(initial_unread)
```

### 5. 单用户处理 (scanner.py - \_process_single_user)

```python
# 获取最后一条消息
last_msg = messages[-1]
is_kefu_message = getattr(last_msg, 'is_self', False)

if is_kefu_message:
    # 客服发的 → 进入 _handle_kefu_last_message
    result = await self._handle_kefu_last_message(...)
else:
    # 客户发的 → 标记已回复，跳过
    self._repository.mark_responded(customer_id)
    return {'status': 'skipped', 'reason': 'Customer already replied'}
```

### 6. 跟进条件判断 (scanner.py - \_handle_kefu_last_message)

```python
# 1. 获取已发送的跟进次数
attempt_count = self._repository.get_attempt_count(customer_id)
attempt_number = attempt_count + 1

# 2. 检查最大次数
if attempt_number > max_followups:
    return {'status': 'skipped', 'reason': 'Max attempts reached'}

# 3. 计算所需延迟
required_delay = self._settings.calculate_required_delay(attempt_number)

# 4. 解析最后消息时间
last_msg_time = parse_wecom_timestamp(last_msg.timestamp)

# 5. 检查时间条件
seconds_elapsed = (now - last_msg_time).total_seconds()
if seconds_elapsed < required_delay:
    return {'status': 'skipped', 'reason': 'Cooling down'}

# 6. 发送跟进消息
success, sent_text = await wecom.send_message(msg_text)
```

---

## 当前判定条件汇总

| 层级           | 判定条件                               | 说明                           |
| -------------- | -------------------------------------- | ------------------------------ |
| **数据库查询** | `last_kefu_time > last_customer_time`  | 客服最后发消息                 |
| **数据库查询** | `previous_attempts < max_followups`    | 未达最大次数                   |
| **数据库查询** | `seconds_elapsed >= required_delay`    | 满足时间延迟 → `is_ready=True` |
| **调度器过滤** | `c.is_ready == True`                   | 只选择就绪的候选人             |
| **调度器过滤** | `c.customer_name not in exclude_users` | 排除 Phase 1 处理过的          |
| **扫描器过滤** | `u.name in target_users`               | 只处理数据库候选人             |
| **扫描器过滤** | `u.name not in exclude_users`          | 排除 Phase 1 处理过的          |
| **扫描器过滤** | `u.unread_count > 0`                   | 必须有红点                     |
| **单用户处理** | `is_kefu_message == True`              | 最后消息是客服发的             |
| **跟进判断**   | `attempt_number <= max_followups`      | 再次检查最大次数               |
| **跟进判断**   | `seconds_elapsed >= required_delay`    | 再次检查时间延迟               |

---

## 问题分析

### 问题 1: 重复判定

时间延迟和最大次数在**三个地方**被判定：

1. `repository.find_candidates()` - 数据库层
2. `scheduler._scan_loop()` - 调度器层（通过 `is_ready`）
3. `scanner._handle_kefu_last_message()` - 扫描器层

**影响**：逻辑分散，维护困难，可能出现不一致。

### 问题 2: 数据库时间 vs UI 时间不一致

- **数据库查询**：使用 `messages` 表中的 `timestamp_parsed`
- **扫描器判断**：使用 UI 提取的 `last_msg.timestamp`

这两个时间可能不一致，导致：

- 数据库认为满足条件（`is_ready=True`）
- 但 UI 提取的时间显示还在冷却中

### 问题 3: 红点依赖

当前 Phase 2 **必须有红点**才能处理用户：

```python
initial_unread = await self._detect_first_page_unread(wecom, serial)
# 只有 unread_count > 0 的用户才会被处理
```

**问题**：如果客服发了消息后，客户没有新消息（无红点），Phase 2 无法处理这个用户。

### 问题 4: target_users 过滤可能遗漏

```python
if target_users is not None:
    result = [u for u in result if u.name in target_users]
```

如果用户名在 UI 显示和数据库中不完全一致（如空格、特殊字符），会导致匹配失败。

---

## 正确的判定逻辑（期望）

Phase 2 候选人应满足以下条件（按顺序）：

1. **最后一条消息是客服发送的**
   - 来源：进入聊天后从 UI 提取
2. **满足时间延迟条件**
   - 计算：`当前时间 - 最后客服消息时间 >= required_delay`
3. **未达到最大跟进次数**
   - 计算：`已发送次数 < max_followups`
4. **没有在 Phase 1 被处理过**
   - 来源：`exclude_users` 列表

---

## 建议优化方向

### 方案 A: 简化为单点判定

将所有判定逻辑集中到 `_handle_kefu_last_message`，移除数据库预筛选：

```python
# scheduler.py
# 不再从数据库查询候选人，直接扫描所有红点用户
result = await self._scanner.scan_all_devices(
    exclude_users=exclude_users,
    target_users=None  # 不限制
)

# scanner.py - _handle_kefu_last_message
# 所有判定逻辑在这里完成
```

**优点**：逻辑集中，易于维护
**缺点**：会进入更多不需要跟进的聊天

### 方案 B: 保持数据库预筛选，但统一时间源

1. 数据库查询只做粗筛（客服最后发消息）
2. 时间判定统一使用 UI 提取的时间
3. 移除数据库层的时间判定

### 方案 C: 不依赖红点

修改 Phase 2 逻辑，不依赖红点检测：

1. 从数据库获取候选人列表
2. 直接搜索/点击用户进入聊天
3. 在聊天中判断是否需要跟进

**优点**：不受红点限制
**缺点**：需要实现用户搜索功能
