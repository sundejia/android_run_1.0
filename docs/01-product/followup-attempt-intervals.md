# 补刀间隔配置功能 (Attempt Intervals)

**功能状态**: ✅ 已完成并测试  
**日期**: 2026-02-06  
**版本**: v1.0

---

## 功能概述

补刀系统支持根据尝试次数配置不同的等待间隔，实现更智能的客户跟进策略。

### 两个关键时间参数

1. **空闲阈值 (idle_threshold_minutes)**
   - 默认值: 30 分钟
   - 作用: 客服最后发消息后，客户无回复超过此阈值，客户进入补刀队列
   - 配置位置: 前端 "Idle Threshold" 设置

2. **补刀间隔 (attempt_intervals)**
   - 默认值: `[60, 120, 180]` 分钟
   - 作用: 每次补刀后的等待时间
     - 第1次补刀后: 等待 60 分钟
     - 第2次补刀后: 等待 120 分钟
     - 第3次补刀后: 等待 180 分钟
   - 配置位置: 前端 "Attempt Intervals" 设置

---

## 工作流程示例

假设配置为:

- `idle_threshold_minutes = 30`
- `attempt_intervals = [60, 120, 180]`
- `max_attempts_per_customer = 3`

### 时间轴

```
T=0: 客服发送消息 "您好，有什么可以帮您？"
  │
  ├─ T=30min: 客户无回复 → 进入补刀队列
  │
  ├─ T=30min: 首次补刀 (attempt #1)
  │   发送: "您好，请问您考虑得怎么样了？"
  │
  ├─ T=90min: 等待60分钟后，第2次补刀 (attempt #2)
  │   发送: "如果有任何问题，欢迎随时联系我"
  │
  ├─ T=210min: 等待120分钟后，第3次补刀 (attempt #3)
  │   发送: "我们有新的优惠活动，要了解一下吗？"
  │
  └─ T=390min: 已达到最大补刀次数 (3次)，不再补刀
```

---

## 前端配置界面

位置: `Follow-up Manage → Settings Tab → Attempt Intervals`

```
⏱️ Attempt Intervals
Wait time after each followup attempt before trying again

┌─ After 1st attempt ─────┐
│  [ 60 ] min             │
└─────────────────────────┘

┌─ After 2nd attempt ─────┐
│  [ 120 ] min            │
└─────────────────────────┘

┌─ After 3rd attempt ─────┐
│  [ 180 ] min            │
└─────────────────────────┘
```

配置项说明:

- 可配置范围: 1-1440 分钟 (1分钟 ~ 24小时)
- 三个间隔可以相同或不同
- 支持实时保存和生效

---

## 技术实现

### 数据库表

**followup_attempts** (主数据库 `wecom_conversations.db`)

```sql
CREATE TABLE followup_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_id TEXT,

    -- 消息追踪
    last_kefu_message_id TEXT NOT NULL,
    last_kefu_message_time DATETIME,
    last_checked_message_id TEXT,

    -- 补刀状态
    max_attempts INTEGER NOT NULL DEFAULT 3,
    current_attempt INTEGER NOT NULL DEFAULT 0,  -- 已补刀次数
    status TEXT NOT NULL DEFAULT 'pending',

    -- 时间戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_followup_at DATETIME,  -- 最后补刀时间

    UNIQUE(device_serial, customer_name)
)
```

关键字段:

- `current_attempt`: 已完成的补刀次数 (0 = 未补刀, 1 = 第1次完成, ...)
- `last_followup_at`: 最后一次补刀的时间戳

### 核心逻辑

**attempts_repository.py → get_pending_attempts()**

```python
def get_pending_attempts(
    self,
    device_serial: str,
    limit: int = 10,
    attempt_intervals: list[int] | None = None,
) -> list[FollowupAttempt]:
    """
    获取待补刀的记录

    逻辑:
    1. 首次补刀 (current_attempt = 0): 立即可执行
    2. 后续补刀: 必须满足间隔时间
       - 第2次: 距离第1次 >= attempt_intervals[0] 分钟
       - 第3次: 距离第2次 >= attempt_intervals[1] 分钟
       - 第N次: 距离第N-1次 >= attempt_intervals[N-2] 分钟
    """
    # 获取符合条件的记录
    for row in rows:
        attempt = self._row_to_attempt(row)

        # 首次补刀，无需检查间隔
        if attempt.current_attempt == 0:
            filtered_attempts.append(attempt)
            continue

        # 后续补刀，检查间隔
        if attempt.last_followup_at:
            interval_index = attempt.current_attempt - 1
            required_interval_minutes = attempt_intervals[interval_index]

            time_since_last = now - attempt.last_followup_at
            minutes_since_last = time_since_last.total_seconds() / 60

            if minutes_since_last >= required_interval_minutes:
                filtered_attempts.append(attempt)
```

### 设置存储

**统一设置服务** (settings database)

```python
# services/settings/models.py
@dataclass
class FollowupSettings:
    idle_threshold_minutes: int = 30
    max_attempts_per_customer: int = 3
    attempt_intervals: list = field(
        default_factory=lambda: [60, 120, 180]
    )
```

存储位置: 主库 SQLite（默认项目根目录 `wecom_conversations.db`，或环境变量 `WECOM_DB_PATH`）中的 **`settings` 表**，`category='followup'`

```json
{
  "category": "followup",
  "key": "attempt_intervals",
  "value": [60, 120, 180],
  "value_type": "json"
}
```

---

## API 接口

### 获取设置

```http
GET /api/followup/settings
```

响应:

```json
{
  "followupEnabled": true,
  "maxFollowupPerScan": 5,
  "idleThresholdMinutes": 30,
  "maxAttemptsPerCustomer": 3,
  "attemptIntervals": [60, 120, 180]
}
```

### 保存设置

```http
POST /api/followup/settings
Content-Type: application/json

{
  "followupEnabled": true,
  "maxFollowupPerScan": 5,
  "idleThresholdMinutes": 30,
  "maxAttemptsPerCustomer": 3,
  "attemptIntervals": [45, 90, 180]
}
```

---

## 测试

### 自动化测试

运行测试脚本:

```bash
python test_attempt_intervals.py
```

测试覆盖:

1. ✅ 设置读取正确性
2. ✅ 首次补刀立即可执行
3. ✅ 第2次补刀间隔判断
4. ✅ 第3次补刀间隔判断
5. ✅ 数据库状态更新

### 手动测试

1. 打开前端 `Follow-up Manage` 页面
2. 切换到 `Settings` 标签
3. 修改 `Attempt Intervals` 配置
4. 点击 `Save Settings`
5. 观察日志输出，确认配置生效

---

## 日志示例

```
╔══════════════════════════════════════════════════════════╗
║             执行待补刀任务                              ║
╚══════════════════════════════════════════════════════════╝
  执行检查: can_exec=True, reason=OK
  补刀配置:
    - 最大补刀数/次: 5
    - 使用AI回复: True
    - AI回调: 已提供
    - 补刀间隔: [60, 120, 180] 分钟

  获取待补刀列表（考虑间隔时间）...
  找到 2 个待补刀目标:
    1. 张三 (第1/3次)
    2. 李四 (第2/3次)
```

---

## 常见问题

### Q1: 为什么有的客户在队列中但不执行补刀？

**A**: 可能是间隔时间未满足。例如:

- 客户刚完成第1次补刀，需要等待 `attempt_intervals[0]` (默认60分钟) 后才能执行第2次
- 检查数据库 `followup_attempts` 表的 `last_followup_at` 和 `current_attempt` 字段

### Q2: 如何修改间隔时间？

**A**: 两种方式:

1. **前端界面**: Follow-up Manage → Settings → Attempt Intervals
2. **直接修改数据库**:
   ```sql
   UPDATE settings
   SET value = '[45, 90, 180]'
   WHERE category = 'followup' AND key = 'attempt_intervals';
   ```

### Q3: 间隔时间是否支持小于60分钟？

**A**: 支持！可以配置 1-1440 分钟 (1分钟 ~ 24小时)。
例如配置 `[15, 30, 60]` 表示:

- 第1次补刀后等待 15 分钟
- 第2次补刀后等待 30 分钟
- 第3次补刀后等待 60 分钟

### Q4: 可以配置超过3次补刀吗？

**A**: 可以！修改 `max_attempts_per_customer` 配置。
如果配置为 5 次补刀，需要提供 5 个间隔时间:

```json
{
  "maxAttemptsPerCustomer": 5,
  "attemptIntervals": [30, 60, 120, 180, 240]
}
```

如果间隔数组长度不足，会使用最后一个间隔值。

---

## 相关文件

### 前端

- `wecom-desktop/src/views/FollowUpManageView.vue` - 配置界面
- `wecom-desktop/src/locales/zh-CN.json` - 中文翻译
- `wecom-desktop/src/locales/en-US.json` - 英文翻译

### 后端

- `wecom-desktop/backend/services/followup/settings.py` - 设置模型
- `wecom-desktop/backend/services/followup/attempts_repository.py` - 数据库逻辑
- `wecom-desktop/backend/services/followup/queue_manager.py` - 队列管理
- `wecom-desktop/backend/routers/followup_manage.py` - API路由
- `wecom-desktop/backend/services/settings/models.py` - 统一设置模型
- `wecom-desktop/backend/services/settings/defaults.py` - 默认值

### 测试

- `test_attempt_intervals.py` - 功能测试脚本

---

## 版本历史

### v1.0 (2026-02-06)

- ✅ 初始实现
- ✅ 前端配置界面
- ✅ 后端逻辑支持
- ✅ 数据库集成
- ✅ 自动化测试
- ✅ 文档完善
