# 补刀覆盖率分析：能否补到所有待补刀的人？

> 创建时间: 2026-02-09  
> 分析对象: `wecom-desktop/backend/services/followup/` 补刀子系统

## 结论（先说答案）

**能补到所有人，但不是一次补完，而是分批逐步覆盖。**

- 每次扫描周期最多执行 **5 人**（`max_followups=5`，可配置）
- 扫描周期默认 **60 秒** 一轮（`scan_interval`，可配置）
- 队列中的待补刀用户会**持久化到数据库**，不会丢失
- 下一轮扫描会继续处理剩余的待补刀用户
- 因此：**20 个待补刀用户大约需要 4 轮（约 4 分钟）全部处理完**

---

## 完整流程图

```
主循环 (每 60 秒一轮)
│
├─ 1. 检测红点用户（首页可见的未读消息）
│     → 全部处理，无数量限制
│     → 仅检测首页，不滚动
│
├─ 2. 红点处理完毕 / 无红点 → 触发补刀检测
│     │
│     ├─ 2a. 从数据库查询最近 24h 对话（LIMIT 50）
│     │     → 判断每个客户的最后消息是客服发的还是客户发的
│     │     → 客服最后发言 + 空闲 > 30分钟 → 入队
│     │     → 客户回复了 → 移出队列
│     │
│     ├─ 2b. 从待补刀队列取最多 5 个（按创建时间 ASC 排序）
│     │     → 检查间隔时间要求（默认: 60/120/180 分钟）
│     │
│     └─ 2c. 执行这 5 个人的补刀
│           → 搜索联系人 → 发消息 → 返回
│
└─ 3. 等待 60 秒 → 下一轮
      → 剩余的待补刀用户在下一轮继续处理
```

---

## 各环节的数量限制

| 环节               | 限制          | 来源                          | 说明                                      |
| ------------------ | ------------- | ----------------------------- | ----------------------------------------- |
| 数据库对话查询     | 50 条         | `LIMIT 50`                    | 最近 24h 有消息的客户，最多取 50 个       |
| 入队筛选           | 无上限        | `process_conversations()`     | 50 条里符合条件的全部入队                 |
| 单次执行数         | **5 个**      | `max_followups=5`             | 每轮扫描最多执行 5 个补刀                 |
| 单客户最大补刀次数 | 3 次          | `max_attempts_per_customer=3` | 第 1/2/3 次，超过后不再补                 |
| 补刀间隔           | 60/120/180 分 | `attempt_intervals`           | 第 1 次后等 60 分钟，第 2 次后等 120 分钟 |
| 扫描间隔           | 60 秒         | `scan_interval`               | 主循环每轮间隔                            |

---

## 关键代码位置

### 1. 数据库查询（50 条限制）

```python
# response_detector.py L2362-2383
query = """
    SELECT c.id, c.name, m.is_from_kefu, m.timestamp_parsed ...
    FROM customers c
    JOIN messages m ON m.customer_id = c.id
    ...
    WHERE m.timestamp_parsed >= ?    -- 最近 24 小时
    AND d.serial = ?                  -- 当前设备
    ORDER BY m.timestamp_parsed DESC
    LIMIT 50                          -- ⚠️ 最多 50 条
"""
```

### 2. 入队逻辑（无数量限制，全部入队）

```python
# queue_manager.py L200-283
for idx, conv in enumerate(conversations, 1):
    if conv.last_message_sender == "customer":
        # 客户回复了 → 移出队列
        repo.mark_customer_replied(...)
    elif conv.last_message_sender == "kefu":
        if time_since >= idle_threshold:
            # 客服最后发言 + 超过阈值 → 入队
            repo.add_or_update(...)   # ✅ 无数量限制
```

### 3. 执行限制（每次 5 个）

```python
# queue_manager.py L403-407
pending = repo.get_pending_attempts(
    self.device_serial,
    limit=settings.max_followups,     # ⚠️ 默认 5
    attempt_intervals=settings.attempt_intervals,
)
```

### 4. 取出顺序（最早入队的优先）

```python
# attempts_repository.py L292-297
rows = conn.execute(
    """SELECT * FROM followup_attempts
       WHERE device_serial = ?
         AND status = 'pending'
         AND current_attempt < max_attempts
       ORDER BY created_at ASC""",   # ⚠️ 最早创建的优先
    (device_serial,),
).fetchall()
```

### 5. 配置定义

```python
# settings.py L39-59
max_followups: int = 5                        # 每次扫描最大补刀数
max_attempts_per_customer: int = 3            # 每客户最多补 3 次
idle_threshold_minutes: int = 30              # 空闲 30 分钟才入队
attempt_intervals: list[int] = [60, 120, 180] # 补刀间隔（分钟）
```

---

## 潜在覆盖盲区

### 盲区 1: 数据库查询的 LIMIT 50

如果一个设备在 24 小时内对话的客户超过 50 人，排名靠后的客户（按消息时间倒序）**不会被查询到**，也就不会进入补刀队列。

- **影响程度**：中等。大多数设备 24h 内活跃客户不会超过 50 个。
- **解决方案**：增大 `LIMIT` 或改为分页查询。

### 盲区 2: 红点优先，补刀被延迟

补刀只在"无红点用户"时才触发。如果设备频繁收到新消息（红点），补刀可能被持续延迟。

- **影响程度**：低。红点处理完毕后自然轮到补刀。
- **缓解**：补刀队列持久化在数据库中，不会丢失。

### 盲区 3: 不滚动 = 红点检测仅限首页

红点用户检测（回复模式）仅扫描首页可见用户，不翻页。但这**不影响补刀**，因为补刀走的是数据库路径，不依赖 UI 滚动。

### 盲区 4: 首页消息数 ≠ 数据库记录数

如果某个客户从未在首页显示过（比如被其他对话覆盖），红点回复可能错过他。但只要客服曾给他发过消息并记录在数据库里，补刀机制仍然能覆盖到他。

---

## "只能补 5 个人"的误解

用户看到的"一次只处理最近的 5 个"这个现象是真实的，但关键是：

1. **不是"最近的 5 个"，而是"最早入队的 5 个"**（`ORDER BY created_at ASC`）
2. **队列是持久化的**，未处理完的会留在数据库
3. **下一轮扫描（60 秒后）会继续处理剩余的**
4. 所以最终所有符合条件的用户都会被补到

### 示例：25 个待补刀用户

| 轮次    | 时间 | 处理       | 剩余 |
| ------- | ---- | ---------- | ---- |
| 第 1 轮 | 0:00 | 用户 1-5   | 20   |
| 第 2 轮 | 1:00 | 用户 6-10  | 15   |
| 第 3 轮 | 2:00 | 用户 11-15 | 10   |
| 第 4 轮 | 3:00 | 用户 16-20 | 5    |
| 第 5 轮 | 4:00 | 用户 21-25 | 0    |

约 5 分钟内全部补完（假设没有新的红点消息打断）。

---

## 可优化方向

| 方向                 | 当前值 | 建议           | 风险                       |
| -------------------- | ------ | -------------- | -------------------------- |
| 增大 `max_followups` | 5      | 可调到 10-15   | 单轮耗时增加，可能错过红点 |
| 缩短 `scan_interval` | 60s    | 可调到 30-45s  | 增加设备负载               |
| 增大数据库 LIMIT     | 50     | 可调到 100-200 | 查询性能轻微下降           |
| 补刀与红点并行       | 串行   | 实现较复杂     | 可能冲突（同时操作设备）   |

> **注意**：`max_followups` 和 `scan_interval` 可以在前端设置页面直接修改，无需改代码。

---

## 相关文件

| 文件                                 | 作用                                        |
| ------------------------------------ | ------------------------------------------- |
| `response_detector.py` L2109-2327    | 补刀触发入口 `_try_followup_if_idle()`      |
| `response_detector.py` L2329-2438    | 数据库对话查询 `_build_conversation_list()` |
| `queue_manager.py` L160-315          | 对话 → 入队逻辑 `process_conversations()`   |
| `queue_manager.py` L380-460          | 执行补刀 `execute_pending_followups()`      |
| `attempts_repository.py` L275-343    | 待补刀查询 `get_pending_attempts()`         |
| `settings.py` L30-59                 | 补刀配置定义 `FollowUpSettings`             |
| `realtime_reply_process.py` L196-230 | 主扫描循环                                  |
| `executor.py`                        | 补刀执行器（搜索 → 发消息 → 返回）          |
