# Follow-up 阶段二：补刀发送实现详解

## ⚠️ 当前实现存在三个 BUG

### BUG 1: Phase 2 错误地依赖红点检测

**Phase 2 应该主动找没有红点的客户发送补刀，但当前实现错误地依赖红点检测。**

#### 当前（错误）逻辑：

```
数据库候选客户 [A, B, C]
        ↓
    检测红点用户 [B, D, E]
        ↓
    取交集 → 只有 [B]
        ↓
    只处理 B，遗漏了 A 和 C！
```

#### 正确逻辑应该是：

```
数据库候选客户 [A, B, C]  (已从数据库判断时间条件)
        ↓
    直接在列表中查找这些客户
        ↓
    进入聊天 → 发送补刀（无需再次判断时间）
```

**BUG 位置**: `scanner.py` 第 125-144 行

---

### BUG 2: 时间判断重复且来源错误

**`find_candidates()` 已经从数据库 `messages` 表判断了时间条件，但 `_handle_kefu_last_message()` 又从 UI 界面重新读取时间判断。**

#### 当前（错误）流程：

```
find_candidates():
  └── 从 messages 表查询 last_kefu_time   ← 数据库时间（正确）
  └── 计算 is_ready = (now - last_kefu_time) >= required_delay
  └── 返回 is_ready=True 的候选

_handle_kefu_last_message():
  └── parse_wecom_timestamp(last_msg.timestamp)   ← UI 界面时间（错误）
  └── 重新判断 seconds_elapsed < required_delay   ← 重复判断
```

#### 正确流程：

```
find_candidates():
  └── 从 messages 表查询时间条件
  └── 返回 is_ready=True 的候选（已经判断过了）

send_followup():
  └── 直接发送，无需再判断时间
```

**BUG 位置**: `scanner.py` 第 381-405 行

---

### BUG 3: 补刀消息未写入 messages 表

**补刀消息只写入了 `followup_attempts` 表，没有写入 `messages` 表，导致：**

1. `find_candidates()` 查询时，无法知道已经发送过补刀
2. 下次查询时，仍然认为"客服最后消息"是原来那条，而不是补刀消息
3. 可能导致重复补刀或时间计算错误

#### 当前（错误）：

```python
# scanner.py _handle_kefu_last_message()
if success:
    self._repository.record_attempt(...)  # 只写入 followup_attempts
    # ❌ 没有写入 messages 表！
```

#### 正确做法：

```python
if success:
    # 1. 写入 followup_attempts
    self._repository.record_attempt(...)

    # 2. 同时写入 messages 表
    self._repository.save_followup_message(
        customer_id=customer_id,
        content=sent_text,
        is_from_kefu=True,
        timestamp_parsed=datetime.now()
    )
```

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                  BackgroundScheduler（调度器）                    │
│                    scheduler.py                                  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                                   ▼
┌───────────────────────┐           ┌───────────────────────────┐
│   Phase 1: 回复检测    │           │   Phase 2: 补刀发送        │
│  ResponseDetector     │           │   FollowUpScanner         │
│  response_detector.py │           │   scanner.py              │
└───────────────────────┘           └───────────────────────────┘
            │                                   │
            └─────────────┬─────────────────────┘
                          ▼
              ┌───────────────────────┐
              │   FollowUpRepository  │
              │   repository.py       │
              │   (数据库操作)         │
              └───────────────────────┘
```

## 二、Phase 2 核心逻辑

### 2.1 触发条件

Phase 2 在 `BackgroundScheduler._scan_loop()` 中被触发：

```python
# scheduler.py (Line 207-247)
# Phase 2: Send follow-up messages to eligible customers
self._logger.info(f"Phase 2: Finding customers who need follow-up...")

# 1. 从数据库查找候选客户
all_candidates = self._repository.find_candidates()

# 2. 过滤条件：
#    - is_ready = True（满足时间延迟）
#    - 未在 Phase 1 处理过
ready_candidates = [
    c for c in all_candidates
    if c.is_ready and c.customer_name not in exclude_users
]

# 3. 执行设备扫描
if ready_candidates:
    target_names = [c.customer_name for c in ready_candidates]
    result = await self._scanner.scan_all_devices(
        exclude_users=exclude_users,
        target_users=target_names
    )
```

### 2.2 候选客户筛选 (repository.py)

```python
def find_candidates(self) -> List[FollowUpCandidate]:
    """
    查找需要跟进的客户候选

    条件：
    1. 有已发送的补刀记录 (status='sent')
    2. 客户尚未回复 (responded=0)
    """

    SELECT
        c.id as customer_id,
        c.name as customer_name,
        c.channel,
        MAX(fa.sent_at) as last_followup_time,
        COUNT(fa.id) as followup_count
    FROM followup_attempts fa
    JOIN customers c ON fa.customer_id = c.id
    WHERE fa.responded = 0
      AND fa.status = 'sent'
    GROUP BY c.id, c.name, c.channel
```

候选客户数据结构：

```python
@dataclass
class FollowUpCandidate:
    customer_id: int
    customer_name: str
    channel: Optional[str]
    last_followup_time: Optional[datetime]
    followup_count: int
    required_delay: int        # 所需等待秒数
    seconds_since_last: int    # 距上次补刀秒数
    is_ready: bool             # 是否满足发送条件
```

### 2.3 延迟计算 (settings.py)

```python
def calculate_required_delay(self, attempt_number: int) -> int:
    """
    计算第 N 次补刀所需的等待时间

    策略：
    - 第1次：initial_delay（默认 180 秒）
    - 第2次及以后：
      - 如果启用指数退避：subsequent_delay * (backoff_multiplier ^ (attempt_number - 2))
      - 否则：subsequent_delay
    """
    settings = self.get_settings()

    if attempt_number <= 1:
        return settings.initial_delay

    if settings.use_exponential_backoff:
        multiplier = settings.backoff_multiplier ** (attempt_number - 2)
        return int(settings.subsequent_delay * multiplier)
    else:
        return settings.subsequent_delay
```

**示例配置**：

| 参数                      | 默认值 | 说明             |
| ------------------------- | ------ | ---------------- |
| `initial_delay`           | 180秒  | 首次补刀等待时间 |
| `subsequent_delay`        | 120秒  | 后续补刀间隔     |
| `max_followups`           | 3      | 最大补刀次数     |
| `use_exponential_backoff` | false  | 是否指数退避     |
| `backoff_multiplier`      | 2.0    | 退避倍数         |

## 三、设备扫描流程 (scanner.py)

### 3.1 `scan_device()` 当前流程（有 BUG）

```
Step 1: 连接设备
    └── adbutils.adb.device(serial=serial)

Step 2: 初始化 WeComService
    └── 复用全量同步的 Config 和 ScrollConfig

Step 3: 启动企业微信
    └── wecom.launch_wecom(wait_for_ready=True)

Step 4: 切换到私聊标签
    └── wecom.switch_to_private_chats()

Step 5: 滚动到顶部
    └── wecom.adb.scroll_to_top()

Step 6: ❌ 错误 - 检测红点用户
    └── _detect_first_page_unread()  ← 问题：只返回有红点的
    └── 与 target_users 取交集     ← 没红点的候选被排除了

Step 7: 处理红点用户队列
    └── 只处理有红点且在 target_users 中的
```

### 3.2 正确的流程应该是

```
Step 1-5: 同上（连接、初始化、打开App、切换私聊、滚动到顶）

Step 6: 直接遍历 target_users（数据库候选客户）
    └── 不依赖红点检测
    └── 在聊天列表中查找每个候选客户

Step 7: 对每个候选客户
    └── click_user_in_list(user_name)  ← 直接按名字找
    └── 如果找不到，滚动查找
    └── 进入聊天 → 判断最后消息 → 发送补刀
```

### 3.2 动态红点检测 (两层优先队列 — 热聊优先)

在一个 scan cycle 内，已聊过又冒红点的用户（hot）始终优先于新陌生人（cold）。

```python
# 两层队列: hot_queue (已聊过又回复) 优先于 cold_queue (新红点)
hot_queue: deque = deque()
cold_queue: deque = deque(initial_unread)
queued_names: Set[str] = {u.name for u in initial_unread}
processed_names: Set[str] = set()

while (hot_queue or cold_queue) and not self._cancel_requested:
    # 热聊用户永远优先
    if hot_queue:
        user = hot_queue.popleft()
    else:
        user = cold_queue.popleft()

    # 处理用户...
    result = await self._process_single_user(wecom, serial, user_name, user_channel)

    # 处理完成后，重新检测红点
    new_unread = await self._detect_first_page_unread(wecom, serial)

    # 分类插入: 已聊过的进 hot_queue, 新陌生人进 cold_queue
    for u in new_unread:
        if u.name in processed_names:
            hot_queue.appendleft(u)          # 热聊优先
            processed_names.discard(u.name)
        elif u.name not in queued_names:
            cold_queue.appendleft(u)         # 新陌生人排后
            queued_names.add(u.name)
```

**流程图**：

```
┌─────────────────────────────────────────────────────────────┐
│  初始红点检测                                                │
│  [A, B, C] → 全部进入 cold_queue                            │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  处理队首用户 A (cold)                                       │
│  - 进入聊天 → AI 回复 → 返回列表                             │
│  processed_names = {A}                                      │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  处理 B (cold) → 回列表 → 重新检测红点                       │
│  发现: A 又回复了(hot) + D 新陌生人(cold)                     │
│  hot_queue: [A]    cold_queue: [D, C]                       │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  下一个: 从 hot_queue 取 A (热聊优先 ✓)                      │
│  再之后: D → C                                              │
└─────────────────────────────────────────────────────────────┘
```

## 四、单用户处理 (scanner.py)

### 4.1 `_process_single_user()` 流程

```python
async def _process_single_user(self, wecom, serial, user_name, user_channel):
    # 1. 点击用户进入聊天
    clicked = await wecom.click_user_in_list(user_name, user_channel)

    # 2. 获取 UI 树并提取消息
    tree = await wecom.adb.get_ui_tree()
    messages = wecom.ui_parser.extract_conversation_messages(tree)

    # 3. 获取最后一条消息
    last_msg = messages[-1]
    is_kefu_message = getattr(last_msg, 'is_self', False)

    # 4. 根据最后消息发送方决定操作
    if is_kefu_message:
        # 客服是最后发送方 → 需要补刀
        result = await self._handle_kefu_last_message(...)
    else:
        # 客户是最后发送方 → 标记已回复
        self._repository.mark_responded(customer_id)
        result = {'status': 'skipped', 'reason': 'Customer already replied'}

    # 5. 返回列表
    await wecom.go_back()

    return result
```

### 4.2 补刀发送逻辑 `_handle_kefu_last_message()`

```python
async def _handle_kefu_last_message(self, wecom, serial, user_name, ...):
    # 1. 获取或创建客户记录
    customer_id = self._repository.find_or_create_customer(user_name, ...)

    # 2. 获取已补刀次数
    attempt_count = self._repository.get_attempt_count(customer_id)
    attempt_number = attempt_count + 1

    # 3. 检查是否超过最大补刀次数
    if attempt_number > max_followups:
        return {'status': 'skipped', 'reason': f'Max attempts reached'}

    # 4. 检查时间条件
    required_delay = self._settings.calculate_required_delay(attempt_number)
    last_msg_time = parse_wecom_timestamp(last_msg.timestamp)

    seconds_elapsed = (now - last_msg_time).total_seconds()
    if seconds_elapsed < required_delay:
        return {'status': 'skipped', 'reason': f'Cooling down'}

    # 5. 生成并发送补刀消息
    msg_text = self._generate_followup_message(attempt_number)
    success, sent_text = await wecom.send_message(msg_text)

    # 6. 记录补刀尝试
    if success:
        self._repository.record_attempt(
            customer_id=customer_id,
            attempt_number=attempt_number,
            status='sent',
            message_content=sent_text
        )
    else:
        self._repository.record_attempt(
            customer_id=customer_id,
            attempt_number=attempt_number,
            status='failed',
            message_content=msg_text,
            error_message='Send failed'
        )

    return {'status': 'sent' if success else 'failed', 'attempt': attempt_number}
```

### 4.3 补刀消息模板

```python
def _generate_followup_message(self, attempt_number: int) -> str:
    """生成跟进消息"""
    messages = {
        1: "您好，请问还有什么需要了解的吗？",
        2: "您好，之前的问题解决了吗？有任何疑问随时联系我。",
        3: "您好，期待您的回复，我们随时为您服务。",
    }
    return messages.get(attempt_number, messages[3])
```

## 五、数据库操作 (repository.py)

### 5.1 核心表结构

```sql
-- 客户表
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    channel TEXT,
    kefu_id INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 补刀尝试记录表
CREATE TABLE followup_attempts (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    message_content TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'sent',      -- 'sent', 'failed', 'cancelled'
    responded INTEGER DEFAULT 0,      -- 0: 未回复, 1: 已回复
    responded_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
```

### 5.2 关键数据库操作

```python
# 记录补刀尝试
def record_attempt(self, customer_id, attempt_number, status, message_content, error_message=None):
    INSERT INTO followup_attempts
    (customer_id, attempt_number, message_content, status, sent_at, error_message)
    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)

# 标记客户已回复
def mark_responded(self, customer_id: int) -> int:
    UPDATE followup_attempts
    SET responded = 1, responded_at = CURRENT_TIMESTAMP
    WHERE customer_id = ? AND responded = 0 AND status = 'sent'

# 获取补刀次数
def get_attempt_count(self, customer_id: int) -> int:
    SELECT COUNT(*) FROM followup_attempts
    WHERE customer_id = ? AND responded = 0 AND status = 'sent'
```

## 六、完整工作流程时序图

```
┌──────────┐     ┌───────────┐     ┌──────────┐     ┌──────────┐     ┌─────────┐
│Scheduler │     │Repository │     │ Scanner  │     │WeComSvc  │     │ Device  │
└────┬─────┘     └─────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬────┘
     │                 │                │                │                │
     │ find_candidates()               │                │                │
     │────────────────>│                │                │                │
     │                 │                │                │                │
     │  candidates[]   │                │                │                │
     │<────────────────│                │                │                │
     │                 │                │                │                │
     │ scan_all_devices(target_users)  │                │                │
     │─────────────────────────────────>│                │                │
     │                 │                │                │                │
     │                 │                │ launch_wecom() │                │
     │                 │                │───────────────>│ ADB commands   │
     │                 │                │                │───────────────>│
     │                 │                │                │                │
     │                 │                │ switch_to_private_chats()      │
     │                 │                │───────────────>│───────────────>│
     │                 │                │                │                │
     │                 │                │ detect_red_dots()              │
     │                 │                │───────────────>│ get_ui_tree() │
     │                 │                │                │───────────────>│
     │                 │                │<───────────────│<───────────────│
     │                 │                │                │                │
     │                 │                │ click_user()   │                │
     │                 │                │───────────────>│───────────────>│
     │                 │                │                │                │
     │                 │                │ extract_messages()              │
     │                 │                │───────────────>│───────────────>│
     │                 │                │<───────────────│<───────────────│
     │                 │                │                │                │
     │                 │ record_attempt()               │                │
     │                 │<───────────────│                │                │
     │                 │                │                │                │
     │                 │                │ send_message() │                │
     │                 │                │───────────────>│───────────────>│
     │                 │                │                │                │
     │  ScanResult     │                │                │                │
     │<─────────────────────────────────│                │                │
     │                 │                │                │                │
```

## 七、配置参数一览

| 参数                      | 类型  | 默认值 | 说明               |
| ------------------------- | ----- | ------ | ------------------ |
| `enabled`                 | bool  | true   | 系统开关           |
| `scan_interval`           | int   | 60     | 扫描间隔（秒）     |
| `max_followups`           | int   | 3      | 最大补刀次数       |
| `initial_delay`           | int   | 180    | 首次补刀等待（秒） |
| `subsequent_delay`        | int   | 120    | 后续补刀间隔（秒） |
| `use_exponential_backoff` | bool  | false  | 指数退避           |
| `backoff_multiplier`      | float | 2.0    | 退避倍数           |
| `enable_operating_hours`  | bool  | false  | 工作时间限制       |
| `start_hour`              | int   | 9      | 开始时间           |
| `end_hour`                | int   | 18     | 结束时间           |

## 八、Phase 1 与 Phase 2 的核心区别

### 8.1 目标对比

| 维度         | Phase 1 (回复检测)            | Phase 2 (补刀发送)                |
| ------------ | ----------------------------- | --------------------------------- |
| **目标用户** | 🔴 有红点的（客户发了新消息） | ⚪ 无红点的（客服发了但客户没回） |
| **触发场景** | 客户主动联系                  | 客服等待客户回复                  |
| **操作内容** | AI 自动回复                   | 发送补刀消息                      |
| **查找方式** | 检测红点                      | 从数据库查询 + 主动查找           |

### 8.2 业务场景

```
场景 A: 客户发消息（有红点）
┌─────────────────────────────────────────┐
│ 客户: "你好，我想咨询一下产品价格"        │  🔴 红点
│                                         │
│ → Phase 1 检测到红点                     │
│ → 进入聊天，AI生成回复                   │
│ → 客服(AI): "您好！请问您想了解哪款产品？" │
└─────────────────────────────────────────┘

场景 B: 客服发了消息，客户没回复（无红点）
┌─────────────────────────────────────────┐
│ 客服: "您好！请问您想了解哪款产品？"       │  ⚪ 无红点
│                                         │
│ ← 等待 3 分钟，客户没回复                │
│                                         │
│ → Phase 2 从数据库发现此客户是候选       │
│ → 主动进入聊天，发送补刀                 │
│ → 客服: "您好，请问还有什么需要了解的吗？" │
└─────────────────────────────────────────┘
```

### 8.3 当前实现流程（有 BUG）

```
┌─────────────────────────────────────────────────────────────────┐
│                       一个扫描周期                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Phase 1: ResponseDetector.detect_and_reply()                   │
│  ├── 检测红点用户 🔴                                             │
│  ├── 进入聊天 → 提取消息 → 写入数据库                            │
│  ├── AI 回复                                                    │
│  ├── 等待新消息（40s超时）                                       │
│  └── 返回已处理用户列表 → exclude_users                          │
│                                                                 │
│                         ↓                                       │
│                     间隔 2 秒                                    │
│                         ↓                                       │
│                                                                 │
│  Phase 2: FollowUpScanner.scan_all_devices()                    │
│  ├── 从数据库查找候选客户（排除 exclude_users）                  │
│  ├── ❌ 错误：检测红点用户，与候选取交集                         │
│  ├── ❌ 问题：无红点的候选被排除了！                             │
│  └── 只处理有红点且在候选中的（遗漏大量）                        │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                    等待 scan_interval 秒                         │
└─────────────────────────────────────────────────────────────────┘
```

## 九、关键代码位置索引

| 功能       | 文件            | 关键方法                       |
| ---------- | --------------- | ------------------------------ |
| 调度循环   | `scheduler.py`  | `_scan_loop()`                 |
| 候选查找   | `repository.py` | `find_candidates()`            |
| 延迟计算   | `settings.py`   | `calculate_required_delay()`   |
| 设备扫描   | `scanner.py`    | `scan_device()`                |
| 红点检测   | `scanner.py`    | `_detect_first_page_unread()`  |
| 单用户处理 | `scanner.py`    | `_process_single_user()`       |
| 补刀发送   | `scanner.py`    | `_handle_kefu_last_message()`  |
| 消息生成   | `scanner.py`    | `_generate_followup_message()` |
| 记录补刀   | `repository.py` | `record_attempt()`             |
| 标记回复   | `repository.py` | `mark_responded()`             |

## 十、BUG 修复方案

### 10.1 修复 BUG 1: 直接遍历数据库候选（不依赖红点）

修改 `scanner.py` 的 `scan_device()` 方法：

```python
async def scan_device(self, device_serial: str, candidates: List[FollowUpCandidate]) -> ScanResult:
    """
    Phase 2 专用：直接遍历数据库候选客户，不检测红点

    Args:
        candidates: find_candidates() 返回的候选列表（已判断时间条件）
    """
    # Step 1-5: 连接、初始化、打开App、切换私聊、滚动到顶
    # ... 同原来

    # Step 6: 直接遍历候选客户（不检测红点！）
    for candidate in candidates:
        if self._cancel_requested:
            break

        user_name = candidate.customer_name
        self._logger.info(f"[{serial}] Processing candidate: {user_name}")

        # 在列表中查找并点击
        clicked = await wecom.click_user_in_list(user_name)
        if not clicked:
            clicked = await self._scroll_and_find_user(wecom, serial, user_name)

        if not clicked:
            self._logger.warning(f"[{serial}] User {user_name} not found, skipping")
            continue

        # 进入聊天，直接发送补刀（无需再判断时间）
        await self._send_followup_directly(wecom, serial, candidate)

        # 返回列表
        await wecom.go_back()
        await asyncio.sleep(0.5)
```

### 10.2 修复 BUG 2: 移除重复的时间判断

新增 `_send_followup_directly()` 方法，直接发送，不再从 UI 判断时间：

```python
async def _send_followup_directly(
    self,
    wecom,
    serial: str,
    candidate: FollowUpCandidate,
) -> Dict[str, Any]:
    """
    直接发送补刀（不再判断时间，find_candidates 已经判断过了）
    """
    customer_id = candidate.customer_id
    user_name = candidate.customer_name
    attempt_number = candidate.previous_attempts + 1

    # 生成并发送补刀消息
    msg_text = self._generate_followup_message(attempt_number)
    self._logger.info(f"[{serial}] Sending follow-up #{attempt_number}: {msg_text[:40]}...")

    success, sent_text = await wecom.send_message(msg_text)

    if success:
        # 1. 写入 followup_attempts
        self._repository.record_attempt(
            customer_id=customer_id,
            attempt_number=attempt_number,
            status='sent',
            message_content=sent_text or msg_text
        )

        # 2. 同时写入 messages 表
        self._repository.save_followup_message(
            customer_id=customer_id,
            content=sent_text or msg_text,
            is_from_kefu=True
        )

        return {'name': user_name, 'status': 'sent', 'attempt': attempt_number}
    else:
        self._repository.record_attempt(
            customer_id=customer_id,
            attempt_number=attempt_number,
            status='failed',
            message_content=msg_text,
            error_message='Send failed'
        )
        return {'name': user_name, 'status': 'failed'}
```

### 10.3 修复 BUG 3: 补刀消息同时写入 messages 表

在 `repository.py` 新增方法：

```python
def save_followup_message(
    self,
    customer_id: int,
    content: str,
    is_from_kefu: bool = True,
) -> int:
    """
    保存补刀消息到 messages 表

    这样 find_candidates() 查询时能正确识别"最后客服消息"是补刀消息
    """
    import hashlib
    from datetime import datetime

    now = datetime.now()
    timestamp_str = now.strftime("%H:%M")

    # 生成消息 hash（与全量同步保持一致）
    hash_input = f"{customer_id}|{content}|{is_from_kefu}|{timestamp_str}"
    message_hash = hashlib.md5(hash_input.encode()).hexdigest()

    with self._connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO messages
                (customer_id, content, message_type, is_from_kefu,
                 timestamp_raw, timestamp_parsed, message_hash, created_at)
                VALUES (?, ?, 'text', ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                customer_id,
                content,
                1 if is_from_kefu else 0,
                timestamp_str,
                now.isoformat(),
                message_hash
            ))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # 消息已存在（hash 冲突）
            return 0
```

### 10.4 修改后的完整数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 2 正确流程                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. find_candidates() 从数据库查询                              │
│     ├── 查询 messages 表，找出客服最后发言的客户                 │
│     ├── 计算 (now - last_kefu_time) >= required_delay          │
│     └── 返回 is_ready=True 的候选                               │
│                                                                 │
│  2. scan_device() 处理候选                                      │
│     ├── 直接遍历候选列表（不检测红点！）                         │
│     ├── 在列表中查找用户（滚动查找）                             │
│     └── 进入聊天                                                │
│                                                                 │
│  3. _send_followup_directly() 发送补刀                          │
│     ├── 生成补刀消息                                            │
│     ├── 发送消息                                                │
│     ├── 写入 followup_attempts 表                               │
│     └── 写入 messages 表 ← 关键！更新"最后客服消息"              │
│                                                                 │
│  4. 下次查询 find_candidates()                                  │
│     └── last_kefu_time 是补刀消息的时间 ← 正确！                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.5 为什么补刀消息必须写入 messages 表？

```
场景：客服发消息后，连续补刀 3 次

❌ 如果只写 followup_attempts：
  messages 表:
    09:00 客服: "您好"  ← last_kefu_time 始终是这个

  find_candidates() 每次查询：
    now - 09:00 = 越来越大 → 一直 is_ready=True → 无限补刀！

✅ 如果同时写 messages：
  messages 表:
    09:00 客服: "您好"
    09:03 客服: "补刀1"  ← last_kefu_time 更新
    09:06 客服: "补刀2"  ← last_kefu_time 更新
    09:09 客服: "补刀3"  ← last_kefu_time 更新

  find_candidates() 每次查询：
    now - 09:09 < required_delay → is_ready=False → 正确冷却
```

### 10.6 调用链修改

```
scheduler.py:
  # 修改前（错误）
  all_candidates = self._repository.find_candidates()  # 查询所有设备的客户
  result = await self._scanner.scan_all_devices_for_candidates(candidates=ready_candidates)

  # 修改后（正确）：为每个设备单独查询该设备对应 kefu 的客户
  for serial in device_serials:
      device_candidates = self._repository.find_candidates(device_serial=serial)
      result = await self._scanner.scan_device_for_candidates(serial, device_candidates)
```

### 10.7 按设备过滤候选客户

修改 `find_candidates()` 添加 `device_serial` 参数：

```python
def find_candidates(self, device_serial: Optional[str] = None):
    # 如果指定了设备，先获取对应的 kefu_id
    kefu_id_filter = None
    if device_serial:
        cursor.execute("""
            SELECT k.id FROM kefus k
            JOIN kefu_devices kd ON k.id = kd.kefu_id
            JOIN devices d ON kd.device_id = d.id
            WHERE d.serial = ?
        """, (device_serial,))
        kefu_row = cursor.fetchone()
        if kefu_row:
            kefu_id_filter = kefu_row[0]

    # 在 SQL 查询中添加 kefu_id 过滤
    if kefu_id_filter is not None:
        base_query += f" AND c.kefu_id = {kefu_id_filter}"
```

### 10.8 多设备 Phase 2 流程

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 2: 为每个设备单独处理                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 发现所有连接的设备 [Device A, Device B]                   │
│                                                             │
│  2. 对于每个设备：                                           │
│     │                                                       │
│     ├── Device A:                                           │
│     │   └── find_candidates("A") → 只查 kefu_A 的客户        │
│     │   └── scan_device_for_candidates("A", 候选列表)        │
│     │                                                       │
│     ├── Device B:                                           │
│     │   └── find_candidates("B") → 只查 kefu_B 的客户        │
│     │   └── scan_device_for_candidates("B", 候选列表)        │
│                                                             │
│  3. 汇总结果                                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
