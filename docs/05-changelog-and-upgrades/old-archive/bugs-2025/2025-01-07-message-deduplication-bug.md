# 消息去重Bug分析报告

**日期**: 2025-01-07
**问题**: 消息去重逻辑存在缺陷，导致部分消息被错误跳过

## 问题描述

在测试过程中发现，聊天记录保存时存在消息跳过的问题。具体表现为：

- 上下两条消息都成功保存了
- 但中间的消息却被跳过了（未保存到数据库）

这种情况明显不正常，说明去重逻辑存在缺陷。

## 根本原因分析

经过代码审查，发现问题源于**消息哈希计算中的两个设计缺陷**：

### 1. 2小时时间桶导致Hash冲突

**位置**: `src/wecom_automation/database/models.py:214-286`

```python
def compute_hash(self) -> str:
    # ...
    # Round down to 2-hour buckets (0, 2, 4, 6, ..., 22)
    ts = self.timestamp_parsed
    bucket_hour = (ts.hour // 2) * 2  # 向下取整到偶数小时
    bucketed = ts.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
    ts_str = bucketed.isoformat()
```

**问题**：使用2小时bucket作为时间戳的模糊匹配，会导致以下场景中的哈希冲突：

| 消息  | 内容   | 原始时间 | Bucket时间 | sequence |
| ----- | ------ | -------- | ---------- | -------- |
| 消息A | "收到" | 21:18    | 20:00      | 0        |
| 消息B | "收到" | 21:50    | 20:00      | 0        |
| 消息C | "好的" | 21:55    | 20:00      | 0        |

- 消息A和消息B的内容、类型、发送方相同
- 时间戳都在同一个2小时bucket（20:00-22:00）
- **sequence值也相同**（见下文）
- 结果：两条消息的hash完全相同，后一条被误判为重复

### 2. Sequence计数器跨批次重置

**位置**: `src/wecom_automation/services/ui_parser.py:993-1020`

```python
def extract_conversation_messages(...):
    # Track sequence numbers for identical messages
    sequence_counters: Dict[str, int] = defaultdict(int)

    for child in children:
        message = self._extract_message_from_row(child, ...)
        # Assign sequence number
        base_key = self._get_message_base_key(message)
        message._sequence = sequence_counters[base_key]
        sequence_counters[base_key] += 1
```

**问题**：

- `sequence_counters`在每次调用`extract_conversation_messages`时都是**新建的**
- 滚动提取消息时，会多次调用此方法
- **每次调用sequence都从0开始重新计数**

**场景示例**：

```
第一次滚动（批次1）：
  消息A: 内容"收到", sequence=0  (base_key="other|text|收到"第1次出现)
  消息B: 内容"好的", sequence=0  (base_key="other|text|好的"第1次出现)

第二次滚动（批次2）：
  消息C: 内容"收到", sequence=0  (base_key="other|text|收到"第1次出现 - 重置了!)
  消息D: 内容"好的", sequence=0  (base_key="other|text|好的"第1次出现 - 重置了!)
```

### 3. 综合效果：Hash冲突导致消息丢失

结合上述两个问题，当满足以下条件时会发生消息丢失：

1. **相同内容**的消息在**不同滚动批次**中提取
2. 这些消息的**时间戳在同一个2小时bucket内**
3. 由于sequence重置，它们的**sequence值相同**

**具体案例**：

| 批次 | 消息 | 内容 | 时间戳 | sequence | Hash计算结果       |
| ---- | ---- | ---- | ------ | -------- | ------------------ |
| #1   | A    | 收到 | 21:18  | 0        | hash_1             |
| #1   | B    | 好的 | 21:20  | 0        | hash_2             |
| #2   | C    | 收到 | 21:50  | 0        | hash_1 (**冲突!**) |
| #2   | D    | 好的 | 21:55  | 0        | hash_2 (**冲突!**) |

- 消息A保存成功 → hash_1
- 消息B保存成功 → hash_2
- 消息C计算hash得到hash_1 → **已存在，跳过**
- 消息D计算hash得到hash_2 → **已存在，跳过**

结果：消息C和D被错误地判定为重复消息而丢失！

## 代码调用链分析

### 消息提取流程

```
wecom_service.extract_conversation_messages()
  └─> 循环滚动，每次调用:
      └─> ui_parser.extract_conversation_messages(tree)
          └─> 新建 sequence_counters = defaultdict(int)
          └─> 为每条消息分配 _sequence
      └─> 添加到 all_messages (使用fingerprint去重，包含原始timestamp)
```

### 消息保存流程

```
customer_syncer.sync()
  └─> message_processor.process(msg, context)
      └─> repository.add_message_if_not_exists(record)
          └─> message.compute_hash()
              └─> 使用 2小时bucket + sequence
          └─> 检查hash是否已存在
          └─> 如果存在则跳过，否则保存
```

### 关键矛盾

- **提取阶段**（wecom_service）：使用原始timestamp进行去重，能够正确区分不同时间的消息
- **保存阶段**（models.py）：使用2小时bucket进行hash计算，可能导致不同时间的消息hash冲突

## 数据库约束

**位置**: `src/wecom_automation/database/schema.py:89`

```sql
CREATE TABLE IF NOT EXISTS messages (
    ...
    message_hash TEXT UNIQUE NOT NULL,  -- SHA256 hash for deduplication
    ...
);
```

`message_hash`字段有**UNIQUE约束**，如果两条消息的hash相同，第二条无法插入。

## 受影响的消息类型

虽然问题理论上影响所有消息类型，但实际影响取决于：

### 高风险场景

1. **文本消息**：用户可能在短时间内发送相同内容
   - 例："收到"、"好的"、"明白"等常见回复

2. **语音消息**：使用duration作为content
   - 例：多条"3秒"的语音在2小时内发送

3. **图片消息**：使用dimensions作为content
   - 例：相同尺寸的图片（如emoji贴图）在2小时内多次发送

### 低风险场景

- 消息内容经常变化
- 时间戳跨度大于2小时
- 同一批次内的相同消息（sequence能正确区分）

## 测试建议

为了验证此bug，可以进行以下测试：

### 测试用例1：文本消息重复

1. 在21:10发送消息"收到"
2. 在21:50再次发送消息"收到"
3. 同步聊天记录
4. **预期结果**：两条消息都保存
5. **实际结果**：第二条被跳过

### 测试用例2：跨2小时边界

1. 在21:55发送消息"好的"
2. 在22:05发送消息"好的"
3. 同步聊天记录
4. **预期结果**：两条消息都保存
5. **实际结果**：待测试（跨bucket可能正确保存）

### 测试用例3：相同内容不同时间

1. 在不同时间（间隔<2小时）发送5条相同消息
2. 同步聊天记录
3. 检查数据库中保存的消息数量
4. **预期结果**：5条
5. **实际结果**：可能只有1-2条

## 修复建议

### 选项1：移除2小时bucket（推荐）

**优点**：

- 简单直接，完全解决问题
- 每条消息都有唯一的hash

**缺点**：

- 滚动提取时，同一消息可能因时间戳显示差异被判定为不同消息
- 需要依赖其他机制（如fingerprint）进行提取阶段的去重

**实现**：修改 `models.py:compute_hash()`

```python
# 使用原始时间戳而不是bucket
ts_str = self.timestamp_raw  # 或 timestamp_parsed.isoformat()
```

### 选项2：使用全局sequence

**优点**：

- 保留2小时bucket的设计意图
- 确保跨批次的消息有不同的sequence

**缺点**：

- 需要跨滚动批次维护sequence计数器
- 实现复杂度高

**实现**：在 `wecom_service` 中维护全局sequence计数器

### 选项3：增强hash输入

**优点**：

- 不改变现有逻辑
- 增加更多区分维度

**缺点**：

- 治标不治本，极端情况下仍可能冲突

**实现**：在hash中加入更多字段（如原始timestamp、滚动批次ID等）

## 影响范围评估

- **严重程度**：高
- **影响范围**：所有使用数据库去重的同步操作
- **数据丢失风险**：是（已发生的消息无法恢复）
- **用户体验影响**：严重（部分对话历史丢失）

## 修复优先级

**P0 - 紧急修复**

理由：

1. 导致数据丢失
2. 影响核心功能
3. 用户已发现问题

## 相关文件

| 文件                                             | 行数     | 问题                             |
| ------------------------------------------------ | -------- | -------------------------------- |
| `src/wecom_automation/database/models.py`        | 214-286  | 2小时bucket导致hash冲突          |
| `src/wecom_automation/services/ui_parser.py`     | 993-1020 | sequence计数器跨批次重置         |
| `src/wecom_automation/services/wecom_service.py` | 682-786  | 提取阶段和保存阶段去重逻辑不一致 |
| `src/wecom_automation/database/schema.py`        | 89       | message_hash UNIQUE约束          |

## 附录：Hash计算代码

```python
def compute_hash(self) -> str:
    """
    Compute a unique hash for this message.

    The hash is based on:
    - customer_id
    - content (or image_dimensions for image messages)
    - message_type
    - is_from_kefu
    - timestamp_bucket (2-hour bucket for fuzzy matching)  <-- 问题所在
    - sequence (from extra_info, for identical messages at same timestamp)
    """
    # Use bucketed timestamp for fuzzy matching
    ts_str = ""
    if self.timestamp_parsed:
        ts = self.timestamp_parsed
        bucket_hour = (ts.hour // 2) * 2  # Round down to nearest even hour
        bucketed = ts.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
        ts_str = bucketed.isoformat()  # <-- 2小时bucket
    elif self.timestamp_raw:
        ts_str = self.timestamp_raw

    # Get sequence from extra_info
    extra = self.get_extra_info_dict()
    seq_str = str(extra.get("sequence", ""))

    # For image/voice/video messages, use dimensions/duration as content
    content_str = self.content or ""
    if self.message_type == "image":
        img_dims = extra.get("image_dimensions", "")
        if img_dims:
            content_str = f"[IMG:{img_dims}]"
    elif self.message_type == "voice":
        voice_dur = extra.get("voice_duration", "")
        if voice_dur:
            content_str = f"[VOICE:{voice_dur}]"
    elif self.message_type == "video":
        vid_dur = extra.get("video_duration", "")
        if vid_dur:
            content_str = f"[VID:{vid_dur}]"

    hash_input = "|".join([
        str(self.customer_id),
        content_str,
        msg_type,
        "1" if self.is_from_kefu else "0",
        ts_str,  # <-- 2小时bucket可能导致冲突
        seq_str,  # <-- 跨批次重置导致冲突
    ])
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
```
