# 补刀间隔时间自定义功能

> **Status**: ✅ Complete | **Date**: 2026-02-02

## 概述

补刀系统支持自定义每次补刀之间的间隔时间，允许灵活控制跟进节奏。用户可以为第1次、第2次、第3次补刀分别设置不同的等待时间（单位：分钟）。

## 功能特性

### 自定义间隔时间

- **默认间隔**: [60, 120, 180] 分钟（1小时、2小时、3小时）
- **可配置范围**: 1-1440 分钟（1分钟到1天）
- **灵活配置**: 每次补刀可以有不同的间隔时间

### 工作原理

```
客户进入补刀队列 (空闲超过阈值)
    │
    ▼
第1次补刀 (current_attempt = 0)
    │ 无需检查间隔，立即执行
    ▼
记录补刀时间
    │
    ▼ 等待 intervals[0] 分钟
    ▼
第2次补刀 (current_attempt = 1)
    │ 检查：距上次补刀 >= intervals[0]？
    ├─ 是 → 执行补刀
    └─ 否 → 跳过，等待下次
    ▼
记录补刀时间
    │
    ▼ 等待 intervals[1] 分钟
    ▼
第3次补刀 (current_attempt = 2)
    │ 检查：距上次补刀 >= intervals[1]？
    ├─ 是 → 执行补刀
    └─ 否 → 跳过，等待下次
    ▼
...
```

### 数据结构

#### 设置存储

```python
# FollowUpSettings
attempt_intervals: List[int] = [60, 120, 180]

# 含义：
# intervals[0] = 第1次补刀后等待时间（第2次补刀的间隔）
# intervals[1] = 第2次补刀后等待时间（第3次补刀的间隔）
# intervals[2] = 第3次补刀后等待时间（第4次补刀的间隔）
# ...
```

#### 数据库记录

```sql
-- followup_attempts 表
CREATE TABLE followup_attempts (
    id INTEGER PRIMARY KEY,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    current_attempt INTEGER NOT NULL DEFAULT 0,  -- 已补刀次数
    max_attempts INTEGER NOT NULL DEFAULT 3,    -- 最大补刀次数
    last_followup_at DATETIME,                  -- 最后补刀时间
    ...
);
```

### 核心实现

#### 间隔时间过滤逻辑

**位置**: `servic../03-impl-and-arch/attempts_repository.py:get_pending_attempts()`

```python
def get_pending_attempts(
    self,
    device_serial: str,
    limit: int = 10,
    attempt_intervals: Optional[List[int]] = None,
) -> List[FollowupAttempt]:
    """
    获取待补刀的记录

    间隔时间检查：
    - current_attempt = 0: 首次补刀，无需检查间隔
    - current_attempt > 0: 必须满足间隔时间要求

    Args:
        attempt_intervals: 补刀间隔时间列表（分钟）
                          [60, 120, 180] 表示：
                          - 第1次补刀后等待60分钟
                          - 第2次补刀后等待120分钟
                          - 第3次补刀后等待180分钟
    """
    if attempt_intervals is None or len(attempt_intervals) == 0:
        attempt_intervals = [60, 120, 180]  # 默认值

    for attempt in all_pending_attempts:
        # 首次补刀，无需检查间隔
        if attempt.current_attempt == 0:
            filtered.append(attempt)
            continue

        # 后续补刀，检查距离上次补刀的时间
        if attempt.last_followup_at:
            # 获取对应的间隔时间
            interval_index = attempt.current_attempt - 1
            if interval_index < len(attempt_intervals):
                required_interval = attempt_intervals[interval_index]
            else:
                # 超出索引，使用最后一个间隔
                required_interval = attempt_intervals[-1] if attempt_intervals else 60

            # 计算距离上次补刀的时间
            time_since_last = now - attempt.last_followup_at
            minutes_since_last = time_since_last.total_seconds() / 60

            # 检查是否满足间隔要求
            if minutes_since_last >= required_interval:
                filtered.append(attempt)
```

### 前端界面

**位置**: `wecom-desktop/src/views/FollowUpManageView.vue`

```vue
<!-- 间隔时间配置 -->
<div class="attempt-intervals">
  <label>⏱️ 补刀间隔时间（分钟）</label>

  <!-- 第1次补刀后的间隔 -->
  <div class="interval-input">
    <span>第1次后:</span>
    <input
      v-model.number="settings.attemptIntervals[0]"
      type="number"
      min="1"
      max="1440"
    />
    <span>分钟</span>
  </div>

  <!-- 第2次补刀后的间隔 -->
  <div class="interval-input">
    <span>第2次后:</span>
    <input
      v-model.number="settings.attemptIntervals[1]"
      type="number"
      min="1"
      max="1440"
    />
    <span>分钟</span>
  </div>

  <!-- 第3次补刀后的间隔 -->
  <div class="interval-input">
    <span>第3次后:</span>
    <input
      v-model.number="settings.attemptIntervals[2]"
      type="number"
      min="1"
      max="1440"
    />
    <span>分钟</span>
  </div>
</div>
```

### API 接口

#### 获取设置

```http
GET /a../03-impl-and-arch/settings
```

**响应**:

```json
{
  "followupEnabled": true,
  "maxFollowupPerScan": 5,
  "attemptIntervals": [60, 120, 180],
  ...
}
```

#### 更新设置

```http
POST /a../03-impl-and-arch/settings
Content-Type: application/json

{
  "followupEnabled": true,
  "maxFollowupPerScan": 5,
  "attemptIntervals": [30, 60, 90],
  ...
}
```

## 使用场景

### 场景1：快速跟进

适用于需要快速跟进的场景（如促销活动）：

```python
attempt_intervals = [15, 30, 60]  # 15分钟、30分钟、1小时
```

### 场景2：温和跟进

适用于不想给客户太大压力的场景：

```python
attempt_intervals = [120, 240, 480]  # 2小时、4小时、8小时
```

### 场景3：每日跟进

适用于长期跟进策略：

```python
attempt_intervals = [1440, 2880, 4320]  # 1天、2天、3天
```

## 边界条件处理

| 场景                    | 处理方式                       |
| ----------------------- | ------------------------------ |
| 空数组 `[]`             | 使用默认值 `[60, 120, 180]`    |
| `None` 值               | 使用默认值 `[60, 120, 180]`    |
| 超出索引范围            | 使用最后一个间隔值             |
| 缺少 `last_followup_at` | 容错处理，允许补刀             |
| 零间隔                  | 立即允许补刀                   |
| 负数间隔                | 当前实现会通过（建议添加验证） |

## 测试覆盖

### 单元测试

**文件**: `wecom-desktop/backend/tests/test_followup_intervals.py`

- ✅ 首次补刀无间隔检查
- ✅ 第二次补刀间隔检查
- ✅ 第三次补刀间隔检查
- ✅ 超出索引时使用最后一个值
- ✅ 多客户混合间隔场景
- ✅ limit 参数正确遵守
- ✅ 默认间隔时间
- ✅ 自定义间隔时间
- ✅ 间隔时间边界值验证
- ✅ API 模型序列化
- ✅ 零间隔处理
- ✅ 负数间隔处理
- ✅ 空数组处理
- ✅ 缺少时间戳容错

### 测试运行

```bash
cd wecom-desktop/backend
pytest tests/test_followup_intervals.py -v
```

**结果**: 15/15 测试通过 ✅

## 配置同步

间隔时间配置通过以下路径同步：

```
前端 UI → API 路由 → SettingsManager → 统一设置服务 → 数据库
         ↓
         ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ←
```

### 相关文件

- **后端设置**: `servic../03-impl-and-arch/settings.py`
- **数据模型**: `servic../03-impl-and-arch/key-modules/models.py`
- **默认值**: `servic../03-impl-and-arch/key-modules/defaults.py`
- **API 路由**: `routers/followup_manage.py`
- **前端视图**: `src/views/FollowUpManageView.vue`

## 最佳实践

1. **间隔时间递增**: 建议间隔时间逐次递增，避免过于频繁的跟进
2. **考虑客户类型**: 不同类型的客户可以设置不同的间隔策略
3. **工作时间限制**: 结合 `enableOperatingHours` 使用，避免非工作时间补刀
4. **监控效果**: 通过统计数据监控不同间隔时间的回复率，优化策略

## 未来改进

- [ ] 添加间隔时间合理性验证（防止负数或过大值）
- [ ] 支持按客户类型设置不同的间隔策略
- [ ] 添加智能间隔建议（基于历史数据）
- [ ] 前端输入验证增强（实时检查）
- [ ] 间隔时间优化建议（基于回复率分析）

## 相关文档

- [补刀系统架构](../03-impl-and-arch/followup-system-logic.md)
- [补刀系统设计](../../wecom-desktop/docs/followup-system-design.md)
- [AI Prompt 结构](../03-impl-and-arch/ai-prompt-structure.md)
- [补刀日志增强](../03-impl-and-arch/followup-logging-enhancement.md)
