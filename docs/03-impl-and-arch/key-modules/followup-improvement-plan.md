# Follow-up 系统改进计划

## 一、当前系统架构

### 1.1 核心组件

```
wecom-desktop/backend/servic../03-impl-and-arch/
├── __init__.py          # 模块初始化
├── models.py            # 数据模型定义
├── settings.py          # 设置管理
├── repository.py        # 数据库操作
├── scanner.py           # 设备扫描器（发送补刀消息）
├── response_detector.py # 回复检测器（检测红点并回复）
├── scheduler.py         # 后台调度器
└── service.py           # 主服务入口
```

### 1.2 数据模型

#### FollowUpCandidate（需要跟进的客户）

```python
@dataclass
class FollowUpCandidate:
    customer_id: int
    customer_name: str
    channel: Optional[str]
    kefu_id: int
    last_kefu_message_time: datetime      # 客服最后发送消息的时间
    last_customer_message_time: Optional[datetime]  # 客户最后回复的时间
    previous_attempts: int                 # 已尝试的补刀次数
    seconds_since_last_kefu_message: int   # 距离最后客服消息的秒数
    required_delay: int                    # 需要等待的延迟（秒）
    is_ready: bool                         # 是否满足发送条件
```

#### FollowUpSettings（跟进设置）

```python
@dataclass
class FollowUpSettings:
    enabled: bool = True                    # 是否启用
    scan_interval: int = 60                 # 扫描间隔（秒）
    max_followups: int = 3                  # 最大补刀次数
    initial_delay: int = 120                # 首次补刀延迟（秒）
    subsequent_delay: int = 120             # 后续补刀延迟（秒）
    use_exponential_backoff: bool = False   # 是否使用指数退避
    backoff_multiplier: float = 2.0         # 退避倍数
    enable_operating_hours: bool = True     # 是否限制工作时间
    start_hour: int = 10                    # 工作开始时间
    end_hour: int = 22                      # 工作结束时间
    use_ai_reply: bool = False              # 是否使用 AI 回复
```

---

## 二、当前工作流程

### 2.1 整体流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                     BackgroundScheduler                          │
│                    (后台调度器 - 定时循环)                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │           Phase 1: 回复检测             │
        │         (ResponseDetector)             │
        │                                        │
        │  1. 打开企业微信                        │
        │  2. 切换到私聊标签                      │
        │  3. 检测第一页红点                      │
        │  4. 对每个红点用户:                     │
        │     - 进入聊天                         │
        │     - 提取消息 → 写入数据库             │
        │     - AI 回复（如果启用）               │
        │     - 等待新消息（40秒）                │
        │  5. 返回列表重新检测                    │
        │  6. 循环直到无红点                      │
        └────────────────────────────────────────┘
                             │
                             │ 收集已处理用户 (exclude_users)
                             ▼
        ┌────────────────────────────────────────┐
        │           Phase 2: 补刀发送             │
        │          (FollowUpScanner)             │
        │                                        │
        │  1. 从数据库查找候选客户                 │
        │     (最后消息来自客服且未回复)           │
        │  2. 过滤:                              │
        │     - 排除 Phase 1 已处理的用户         │
        │     - 检查是否满足延迟条件              │
        │     - 检查是否达到最大补刀次数          │
        │  3. 对每个候选客户:                     │
        │     - 进入聊天                         │
        │     - 发送补刀消息                      │
        │     - 记录尝试到 followup_attempts     │
        └────────────────────────────────────────┘
                             │
                             │ 等待 scan_interval 秒
                             ▼
                        下一轮循环
```

### 2.2 Phase 1: 回复检测 (ResponseDetector)

```python
# response_detector.py - detect_and_reply()

流程:
1. 打开企业微信
2. 切换到私聊标签
3. 只检测第一页红点（不滚动）
4. 对有红点的用户：
   - 进入聊天界面
   - 提取聊天消息
   - 写入数据库（messages 表）
   - 标记客户已回复（mark_responded）
   - 如果启用 AI 回复：生成并发送回复
   - 等待新消息（interactive_wait_timeout = 40s）
5. 返回列表后重新检测红点
6. 优先处理新出现的红点
7. 循环直到没有红点
```

**关键代码路径**:

- `ResponseDetector.detect_and_reply()` → 主入口
- `WeComService.extract_private_chat_users()` → 提取用户列表和红点
- `WeComService.extract_conversation()` → 提取聊天消息
- `repository.mark_responded()` → 标记客户已回复

### 2.3 Phase 2: 补刀发送 (FollowUpScanner)

```python
# scanner.py - scan_devices()

流程:
1. 从数据库查找候选客户:
   - 条件: 最后一条消息是客服发送的
   - 且客户没有回复

2. 对每个候选客户:
   - 检查是否在 exclude_users 中（Phase 1 已处理）
   - 检查已尝试次数 < max_followups
   - 计算需要的延迟时间
   - 检查是否满足延迟条件（is_ready）

3. 如果满足条件:
   - 导航到该客户的聊天界面
   - 生成补刀消息（AI 或模板）
   - 发送消息
   - 记录到 followup_attempts 表
```

**候选客户查询 SQL**:

```sql
WITH LastMessages AS (
    SELECT
        customer_id,
        MAX(CASE WHEN is_from_kefu = 1 THEN timestamp_parsed END) as last_kefu_time,
        MAX(CASE WHEN is_from_kefu = 0 THEN timestamp_parsed END) as last_customer_time
    FROM messages
    GROUP BY customer_id
)
SELECT c.*, lm.*
FROM customers c
JOIN LastMessages lm ON c.id = lm.customer_id
WHERE lm.last_kefu_time IS NOT NULL
  AND (lm.last_customer_time IS NULL OR lm.last_kefu_time > lm.last_customer_time)
```

### 2.4 延迟计算逻辑

```python
def calculate_required_delay(attempt_number: int) -> int:
    """
    计算所需延迟时间

    - 第1次: initial_delay（默认 120s）
    - 第2次+: subsequent_delay * multiplier^(n-2)

    示例 (initial=120s, subsequent=120s, multiplier=2):
      - Attempt 1: 120s
      - Attempt 2: 120s * 2^0 = 120s
      - Attempt 3: 120s * 2^1 = 240s
      - Attempt 4: 120s * 2^2 = 480s
    """
```

---

## 三、数据库表结构

### 3.1 followup_attempts（跟进尝试记录）

```sql
CREATE TABLE followup_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,    -- 第几次补刀
    status TEXT NOT NULL,               -- 'pending', 'sent', 'failed'
    message_content TEXT,               -- 发送的消息内容
    message_preview TEXT,               -- 消息预览（前50字）
    responded INTEGER DEFAULT 0,        -- 是否已回复
    response_time_seconds INTEGER,      -- 回复耗时（秒）
    created_at TIMESTAMP,
    sent_at TIMESTAMP,
    responded_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
```

### 3.2 followup_settings（跟进设置）

```sql
CREATE TABLE followup_settings (
    id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    scan_interval_seconds INTEGER DEFAULT 60,
    max_followups INTEGER DEFAULT 3,
    initial_delay_seconds INTEGER DEFAULT 120,
    subsequent_delay_seconds INTEGER DEFAULT 120,
    use_exponential_backoff INTEGER DEFAULT 0,
    backoff_multiplier REAL DEFAULT 2.0,
    enable_operating_hours INTEGER DEFAULT 1,
    start_hour INTEGER DEFAULT 10,
    end_hour INTEGER DEFAULT 22,
    use_ai_reply INTEGER DEFAULT 0,
    updated_at TIMESTAMP
);
```

---

## 四、当前问题和限制

### 4.1 已知问题

| 问题             | 描述                                   | 影响                         |
| ---------------- | -------------------------------------- | ---------------------------- |
| 红点检测仅第一页 | 只检测私聊列表第一页的红点             | 可能遗漏列表下方的用户消息   |
| 延迟计算基准     | 基于最后客服消息时间，而非最后补刀时间 | 多次补刀的延迟可能不准确     |
| 无黑名单支持     | 补刀系统不支持黑名单过滤               | 可能向不想打扰的客户发送消息 |
| AI 回复上下文    | AI 回复可能缺少足够的对话上下文        | 回复可能不够相关             |

### 4.2 待改进项

1. **红点检测范围** - 是否需要滚动检测更多用户
2. **补刀消息模板** - 支持更灵活的模板配置
3. **补刀触发条件** - 是否基于客户行为动态调整
4. **统计和报表** - 补刀效果的统计分析
5. **黑名单集成** - 与全局黑名单系统联动

---

## 五、改进方向（待讨论）

### 5.1 短期改进

- [ ] 补刀延迟基准改为最后补刀时间
- [ ] 集成黑名单过滤
- [ ] 补刀消息模板管理
- [ ] 更详细的日志和统计

### 5.2 中期改进

- [ ] 智能补刀策略（基于客户响应率）
- [ ] 多设备负载均衡
- [ ] 补刀效果分析报表

### 5.3 长期改进

- [ ] 基于 AI 的补刀时机预测
- [ ] 客户分群和差异化策略
- [ ] A/B 测试框架

---

## 六、API 端点

### 6.1 Follow-up 相关 API

| 端点                                            | 方法      | 描述           |
| ----------------------------------------------- | --------- | -------------- |
| `/a../03-impl-and-arch/settings`                | GET       | 获取跟进设置   |
| `/a../03-impl-and-arch/settings`                | PUT       | 更新跟进设置   |
| `/a../03-impl-and-arch/start`                   | POST      | 启动跟进扫描   |
| `/a../03-impl-and-arch/stop`                    | POST      | 停止跟进扫描   |
| `/a../03-impl-and-arch/status`                  | GET       | 获取扫描状态   |
| `/a../03-impl-and-arch/stats`                   | GET       | 获取统计数据   |
| `/a../03-impl-and-arch/analytics/response-rate` | GET       | 获取响应率分析 |
| `/a../03-impl-and-arch/ws`                      | WebSocket | 实时日志流     |

---

_文档创建时间: 2026-01-02_
_最后更新: 2026-01-02_
