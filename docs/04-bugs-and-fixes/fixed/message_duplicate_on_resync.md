# Bug 分析：回复消息重复写入数据库

> 时间: 2026-01-19  
> 状态: ✅ 已修复

---

## 问题描述

客服发送消息后存入数据库，再次同步时，同一条消息会再次被写入数据库，导致消息重复。

---

## 根因分析

### 消息去重机制

系统使用 `message_hash` 进行消息去重，哈希值计算包含以下字段：

- `customer_id`
- `content`
- `message_type`
- `is_from_kefu`
- `timestamp_bucket`（2小时时间桶）
- `sequence`

### 问题流程

```
1. 客服发送消息 "这边把照片提交审核一下"
2. _store_sent_message 使用当前时间 12:30 存入数据库
   - timestamp_parsed = 2026-01-19 12:30:00+08:00
   - timestamp_bucket = 12:00（12和13点都落在12时间桶）
   - hash = sha256("123|这边把照片提交审核一下|text|1|2026-01-19T12:00:00+08:00|")

3. 再次同步，从UI读取消息
   - UI显示时间可能是 "12:30" 或 "下午 12:30"
   - TimestampParser 解析后可能产生不同的 timestamp_parsed
   - 如果解析结果落在不同的2小时桶，hash不同 → 重复写入！
```

### 问题代码

**位置 1**: `customer_syncer.py:_store_sent_message`

```python
# 使用当前时间
now = datetime.now(tz)
timestamp_raw = now.strftime("%H:%M")  # 格式: 14:30

record = MessageRecord(
    customer_id=context.customer_id,
    content=message_content,
    message_type=MessageType.TEXT,
    is_from_kefu=True,
    timestamp_raw=timestamp_raw,
    timestamp_parsed=now,  # 精确时间
)
```

**位置 2**: 同步时从UI读取

```python
# TextMessageHandler.process
timestamp_raw, timestamp_parsed = self._get_parsed_timestamp(message)
# timestamp_raw 来自UI，可能是 "12:30" 或 "下午" 等相对时间
# timestamp_parsed 通过 TimestampParser 解析，可能与存储时间略有不同
```

---

## 解决方案

### 方案 A: 检查内容+发送者去重（推荐）

对于 `is_from_kefu=True` 的消息，先检查数据库中是否已有相同内容的客服消息：

**修改**: `text.py:TextMessageHandler.process`

```python
async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
    content = self._get_content(message)
    is_from_kefu = self._is_from_kefu(message)

    # 对于客服消息，先检查是否已存在相同内容
    if is_from_kefu:
        existing = self._check_recent_kefu_message(context.customer_id, content)
        if existing:
            self._logger.debug(f"Kefu message already exists: {content[:30]}...")
            return MessageProcessResult(added=False, ...)

    # 正常流程
    ...
```

### 方案 B: 存储时使用更宽松的时间桶

将2小时时间桶改为4小时或更大。

### 方案 C: 客服消息使用内容哈希（无时间）

对于 `is_from_kefu=True` 的消息，哈希计算时忽略时间戳。

---

## 推荐方案

**方案 A** - 在消息处理器中添加客服消息的内容去重检查。

---

## 修复文件清单

1. `src/wecom_automation/services/message/handlers/text.py`
   - 添加客服消息去重检查

2. `src/wecom_automation/database/repository.py`
   - 添加 `get_recent_kefu_message_by_content` 方法
