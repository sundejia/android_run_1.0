# Follow-up 第二阶段逻辑分析

## 概述

Follow-up 系统分为两个阶段：

- **Phase 1 (Response Detection)**: 检测红点用户，进入聊天，提取消息，AI回复，交互等待
- **Phase 2 (Follow-up Scan)**: 对数据库中"客服最后发消息但客户未回复"的用户发送跟进消息

本文档详细分析 **Phase 2** 的逻辑实现。

---

## 文件结构

```
wecom-desktop/backend/servic../03-impl-and-arch/
├── scanner.py           # Phase 2 核心逻辑
├── scheduler.py         # 调度器，协调 Phase 1 和 Phase 2
├── response_detector.py # Phase 1 核心逻辑
├── repository.py        # 数据库操作
├── settings.py          # 设置管理
├── models.py            # 数据模型
└── service.py           # 主服务入口
```

---

## Phase 2 触发流程

### 1. 调度器触发 (scheduler.py)

```python
# scheduler.py: _scan_loop()

# Phase 1: 检测客户回复
response_result = await self._detector.detect_and_reply()

# 收集 Phase 1 处理过的用户（排除列表）
exclude_users = [...]

# Phase 2: 从数据库查找候选客户
all_candidates = self._repository.find_candidates()

# 过滤：必须 is_ready=True 且不在排除列表中
ready_candidates = [
    c for c in all_candidates
    if c.is_ready and c.customer_name not in exclude_users
]

# 执行扫描
result = await self._scanner.scan_all_devices(
    exclude_users=exclude_users,
    target_users=[c.customer_name for c in ready_candidates]
)
```

### 2. 候选客户查询逻辑 (repository.py)

```sql
-- find_candidates() 查询逻辑
SELECT
    c.id as customer_id,
    c.name as customer_name,
    c.channel,
    c.kefu_id,
    -- 最后一条客服消息时间
    MAX(CASE WHEN m.is_from_kefu = 1 THEN m.timestamp_parsed END) as last_kefu_message_time,
    -- 最后一条客户消息时间
    MAX(CASE WHEN m.is_from_kefu = 0 THEN m.timestamp_parsed END) as last_customer_message_time,
    -- 已发送的跟进次数
    COUNT(fa.id) as previous_attempts
FROM customers c
JOIN messages m ON c.id = m.customer_id
LEFT JOIN followup_attempts fa ON c.id = fa.customer_id AND fa.status = 'sent'
GROUP BY c.id
-- 关键条件：客服最后发消息 > 客户最后发消息（或客户从未发消息）
HAVING last_kefu_message_time > COALESCE(last_customer_message_time, '1970-01-01')
```

### 3. 候选客户数据模型

```python
@dataclass
class FollowUpCandidate:
    customer_id: int
    customer_name: str
    channel: Optional[str]
    kefu_id: int
    last_kefu_message_time: datetime
    last_customer_message_time: Optional[datetime]
    previous_attempts: int           # 已发送的跟进次数
    seconds_since_last_kefu_message: int  # 距离上次客服消息的秒数
    required_delay: int              # 所需延迟时间
    is_ready: bool                   # 是否满足发送条件
```

---

## Phase 2 核心流程 (scanner.py)

### 整体流程图

```
scan_all_devices()
        │
        ▼
┌─────────────────────────────────────────┐
│ 1. 发现所有连接的设备                    │
│    _discover_devices()                  │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 2. 并行扫描所有设备                      │
│    asyncio.gather(                      │
│      scan_device(serial_1),             │
│      scan_device(serial_2),             │
│      ...                                │
│    )                                    │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 3. 聚合结果                              │
│    - 合并所有设备的扫描结果              │
│    - 统计发送成功/失败数量               │
└─────────────────────────────────────────┘
```

### 单设备扫描流程 (scan_device)

```
scan_device(serial)
        │
        ▼
┌─────────────────────────────────────────┐
│ Step 1: 连接设备                         │
│ adbutils.adb.device(serial=serial)      │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Step 2: 初始化 WeComService              │
│ config = Config(device_serial=serial)   │
│ wecom = WeComService(config)            │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Step 3: 启动企业微信                     │
│ wecom.launch_wecom(wait_for_ready=True) │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Step 4: 切换到私聊列表                   │
│ wecom.switch_to_private_chats()         │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Step 5: 滚动到顶部                       │
│ wecom.adb.scroll_to_top()               │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Step 6: 检测首页红点用户                 │
│ _detect_first_page_unread()             │
│ - 只检测第一页，不滚动                   │
│ - 过滤 exclude_users 和 target_users    │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Step 7: 使用队列处理红点用户             │
│ user_queue = deque(initial_unread)      │
│ while user_queue:                       │
│   user = user_queue.popleft()           │
│   _process_single_user(user)            │
│   # 处理完后重新检测红点                 │
│   new_unread = _detect_first_page_unread()│
│   # 新红点加入队首（优先处理）           │
│   user_queue.appendleft(new_users)      │
└─────────────────────────────────────────┘
```

### 单用户处理流程 (\_process_single_user) - 当前实现

```
_process_single_user(user_name)
        │
        ▼
┌─────────────────────────────────────────┐
│ 1. 点击用户进入聊天                      │
│ wecom.click_user_in_list(user_name)     │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 2. 获取 UI 树并提取消息                  │
│ tree = await wecom.adb.get_ui_tree()    │
│ messages = ui_parser.extract_conversation_messages(tree) │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 3. 获取最后一条消息                      │
│ last_msg = messages[-1]                 │
│ is_kefu_message = last_msg.is_self      │
└───────────────────┬─────────────────────┘
                    │
            ┌───────┴───────┐
            │               │
            ▼               ▼
      is_kefu=True    is_kefu=False
      (客服发的)       (客户发的)
            │               │
            ▼               ▼
┌───────────────────┐ ┌───────────────────┐
│ _handle_kefu_     │ │ 标记已回复        │
│ last_message()    │ │ mark_responded()  │
│ - 检查跟进条件    │ │ 跳过此用户        │
│ - 发送跟进消息    │ │                   │
└─────────┬─────────┘ └─────────┬─────────┘
          │                     │
          └──────────┬──────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│ 4. 返回聊天列表                          │
│ wecom.go_back()                         │
└─────────────────────────────────────────┘
```

### 跟进条件判断 (\_handle_kefu_last_message) - 当前实现

```python
async def _handle_kefu_last_message(self, wecom, serial, user_name, user_channel, last_msg):
    # 1. 获取/创建客户
    customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)

    # 2. 获取已发送的跟进次数
    attempt_count = self._repository.get_attempt_count(customer_id)
    attempt_number = attempt_count + 1

    # 3. 检查是否超过最大跟进次数
    settings = self._settings.get_settings()
    if attempt_number > settings.max_followups:
        return {'status': 'skipped', 'reason': f'Max attempts reached ({attempt_count}/{max_followups})'}

    # 4. 计算所需延迟时间
    required_delay = self._settings.calculate_required_delay(attempt_number)

    # 5. 解析最后消息时间，检查是否满足延迟条件
    last_msg_time = parse_wecom_timestamp(last_msg.timestamp)
    seconds_elapsed = (now - last_msg_time).total_seconds()

    if seconds_elapsed < required_delay:
        return {'status': 'skipped', 'reason': f'Cooling down ({seconds_elapsed}s < {required_delay}s)'}

    # 6. 生成并发送跟进消息（当前使用固定模板）
    msg_text = self._generate_followup_message(attempt_number)
    success, sent_text = await wecom.send_message(msg_text)

    # 7. 记录跟进尝试
    self._repository.record_attempt(
        customer_id=customer_id,
        attempt_number=attempt_number,
        status='sent' if success else 'failed',
        message_content=sent_text or msg_text
    )
```

---

## 延迟计算逻辑 (settings.py)

```python
def calculate_required_delay(self, attempt_number: int) -> int:
    """
    计算所需延迟时间

    attempt_number=1: 首次跟进，使用 initial_delay
    attempt_number>1: 后续跟进，使用 subsequent_delay（可选指数退避）
    """
    settings = self.get_settings()

    if attempt_number <= 1:
        return settings.initial_delay

    if settings.use_exponential_backoff:
        # 指数退避: subsequent_delay * (multiplier ^ (attempt_number - 2))
        exponent = attempt_number - 2
        return int(settings.subsequent_delay * (settings.backoff_multiplier ** exponent))
    else:
        return settings.subsequent_delay
```

### 延迟示例

| 配置                                                      | 第1次 | 第2次 | 第3次 | 第4次 |
| --------------------------------------------------------- | ----- | ----- | ----- | ----- |
| initial=120s, subsequent=120s, backoff=false              | 120s  | 120s  | 120s  | 120s  |
| initial=120s, subsequent=120s, backoff=true, multiplier=2 | 120s  | 120s  | 240s  | 480s  |

---

## 跟进消息模板（当前实现）

```python
def _generate_followup_message(self, attempt_number: int) -> str:
    messages = {
        1: "您好，请问还有什么需要了解的吗？",
        2: "您好，之前的问题解决了吗？有任何疑问随时联系我。",
        3: "您好，期待您的回复，我们随时为您服务。",
    }
    return messages.get(attempt_number, messages[3])
```

---

## Phase 1 vs Phase 2 对比（已优化）

| 特性             | Phase 1 (Response Detection)        | Phase 2 (Follow-up Scan)                    |
| ---------------- | ----------------------------------- | ------------------------------------------- |
| **触发条件**     | 有红点（未读消息）                  | 数据库中客服最后发消息的客户                |
| **检测范围**     | 只检测第一页红点                    | 只检测第一页红点（过滤 target_users）       |
| **进入聊天后**   | 提取消息 → 存储 → AI回复 → 交互等待 | 提取消息 → 判断发送者 → 发送跟进 → 交互等待 |
| **消息存储**     | ✅ 存储到数据库                     | ✅ 存储到数据库                             |
| **AI回复**       | ✅ 始终使用 AI 生成回复             | ✅ 根据 `use_ai_reply` 设置                 |
| **交互等待**     | ✅ 40秒等待新消息（最多10轮）       | ✅ 20秒等待新消息（1轮）                    |
| **延迟控制**     | ❌ 无                               | ✅ 根据设置计算延迟                         |
| **最大次数限制** | ❌ 无                               | ✅ max_followups                            |

---

## 数据库表

### followup_attempts (跟进记录表)

| 字段                  | 类型      | 说明                |
| --------------------- | --------- | ------------------- |
| id                    | INTEGER   | 主键                |
| customer_id           | INTEGER   | 客户ID (外键)       |
| attempt_number        | INTEGER   | 第几次跟进          |
| status                | TEXT      | sent/failed/pending |
| message_content       | TEXT      | 发送的完整消息      |
| message_preview       | TEXT      | 消息预览 (前50字符) |
| responded             | INTEGER   | 是否已回复 (0/1)    |
| response_time_seconds | INTEGER   | 回复耗时 (秒)       |
| created_at            | TIMESTAMP | 创建时间            |
| sent_at               | TIMESTAMP | 发送时间            |
| responded_at          | TIMESTAMP | 回复时间            |
| error_message         | TEXT      | 错误信息            |

---

## 当前问题分析

### 问题 1: Phase 2 不存储发送的消息 ✅ 已解决

**现状**: ~~Phase 2 发送的跟进消息只记录到 `followup_attempts` 表，不存储到 `messages` 表~~

**解决方案**: 在 `scanner.py` 的 `_handle_kefu_last_message` 方法中，发送成功后调用 `_store_sent_message` 方法将消息同时存储到 `messages` 表。

```python
# scanner.py: _handle_kefu_last_message()
if success:
    self._repository.record_attempt(...)

    # 新增：存储发送的消息到 messages 表
    await self._store_sent_message(customer_id, sent_text or msg_text, serial)
```

新增方法 `_store_sent_message`:

```python
async def _store_sent_message(self, customer_id: int, content: str, serial: str) -> None:
    """存储发送的跟进消息到 messages 表"""
    record = MessageRecord(
        customer_id=customer_id,
        content=content,
        message_type=MessageType.TEXT,
        is_from_kefu=True,  # 跟进消息是客服发送的
        timestamp_raw=now.strftime("%H:%M"),
        timestamp_parsed=now,
    )
    repo = ConversationRepository(self._repository._db_path)
    repo.add_message_if_not_exists(record)
```

### 问题 2: Phase 2 的 AI 回复功能需要手动开启 ✅ 已解决

**现状**:

- Phase 2 默认使用 `_generate_followup_message()` 返回固定模板消息
- 勾选 **"启用 AI 生成补刀消息"** 后会使用 AI 生成跟进消息

**实现代码**:

```python
# scanner.py: _handle_kefu_last_message()
settings = self._settings.get_settings()
if settings.use_ai_reply:
    self._logger.info(f"[{serial}]   Generating AI follow-up message...")
    msg_text = await self._generate_ai_followup_message(user_name, messages, serial, attempt_number)
    if not msg_text:
        msg_text = self._generate_followup_message(attempt_number)  # fallback
else:
    msg_text = self._generate_followup_message(attempt_number)
```

### 问题 3: Phase 2 没有交互等待 ✅ 已解决

**现状**: ~~Phase 2 发送消息后立即返回列表，不等待客户回复~~

**解决方案**: 在 `scanner.py` 中添加 `_interactive_wait_loop` 方法，发送跟进消息后等待客户回复（20秒超时）。

**实现逻辑**:

```python
# scanner.py: _handle_kefu_last_message()
if success:
    # ... 记录和存储消息 ...

    # 交互等待：等待客户回复（20秒超时）
    customer_replied = await self._interactive_wait_loop(
        wecom, serial, user_name, user_channel, customer_id,
        current_messages, timeout=20
    )
```

**交互等待流程**:

```
发送跟进消息
    │
    ▼
┌─────────────────────────────────────────┐
│ 等待客户回复（每3秒检测一次）            │
│ - 超时时间：20秒                         │
│ - 检测新的客户消息（is_self=False）      │
└───────────────────┬─────────────────────┘
                    │
            ┌───────┴───────┐
            │               │
            ▼               ▼
      客户回复了        超时无回复
            │               │
            ▼               ▼
┌───────────────────┐ ┌───────────────────┐
│ 1. 存储客户消息   │ │ 返回列表          │
│ 2. 标记已回复     │ │                   │
│ 3. AI回复（可选） │ │                   │
│ 4. 返回列表       │ │                   │
└───────────────────┘ └───────────────────┘
```

**与 Phase 1 的区别**:

| 特性     | Phase 1      | Phase 2                |
| -------- | ------------ | ---------------------- |
| 超时时间 | 40秒         | 20秒                   |
| 最大轮数 | 10轮         | 1轮（客户回复后退出）  |
| 回复方式 | 始终 AI 回复 | 根据 use_ai_reply 设置 |
