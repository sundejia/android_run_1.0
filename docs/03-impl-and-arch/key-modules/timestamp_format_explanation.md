# 时间戳格式说明

## 问题描述

在数据库中存储 `timestamp_parsed` 时，可能会看到两种不同的时间戳格式：

1. **带时区的格式**: `2025-12-28 17:40:00+08:00`
2. **带微秒的格式**: `2026-01-01 14:14:51.467187`

## +08:00 的含义

`+08:00` 是**时区偏移量（Timezone Offset）**，表示该时间比协调世界时（UTC）快 8 小时。

- **UTC (Coordinated Universal Time)**: 世界标准时间
- **+08:00**: UTC+8，即**东八区**时间
- **对应时区**: 中国标准时间（CST - China Standard Time）、香港时间、台湾时间等

### 示例

```
2025-12-28 17:40:00+08:00
```

这表示：

- **本地时间**: 2025年12月28日 17:40:00（下午5点40分）
- **UTC时间**: 2025年12月28日 09:40:00（上午9点40分，减去8小时）

## 两种时间戳格式的区别

### 1. 带时区偏移的格式 (`+08:00`)

```
2025-12-28 17:40:00+08:00
```

**特点：**

- ✅ 包含时区信息，明确表示是哪个时区的时间
- ✅ 可以准确转换到其他时区
- ✅ 推荐用于存储数据库（标准化格式）
- ✅ Python `datetime` 对象的 `timezone-aware` 格式

**来源：**

- `TimestampParser` 解析后的时间戳
- 使用 `ZoneInfo("Asia/Shanghai")` 创建的时间对象

### 2. 带微秒的格式（无时区）

```
2026-01-01 14:14:51.467187
```

**特点：**

- ⚠️ 不包含时区信息（naive datetime）
- ⚠️ 精度到微秒（6位小数）
- ⚠️ 假设是本地时区的时间
- ⚠️ 不推荐用于数据库存储（除非明确知道时区）

**来源：**

- Python `datetime.now()` 创建的本地时间
- 程序内部生成的当前时间

## 数据库存储建议

### ✅ 推荐格式

```python
# 带时区的格式（推荐）
timestamp_parsed = datetime(2025, 12, 28, 17, 40, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
# 存储为: 2025-12-28 17:40:00+08:00
```

**优点：**

- 明确时区，避免歧义
- 可以准确进行时间比较和计算
- 符合国际化标准

### ⚠️ 不推荐格式

```python
# 无时区的格式（不推荐）
timestamp_parsed = datetime.now()
# 存储为: 2026-01-01 14:14:51.467187
```

**问题：**

- 缺少时区信息，容易产生歧义
- 跨时区应用时会出现问题
- 与解析的时间戳格式不一致

## 当前实现

### TimestampParser 的解析结果

`TimestampParser` 解析的时间戳**总是带时区的**：

```python
from wecom_automation.services.timestamp_parser import TimestampParser

parser = TimestampParser(timezone="Asia/Shanghai")
parsed = parser.parse("14:30")  # 今天下午2:30

# 结果: 2026-01-01 14:30:00+08:00
# ✅ 包含 +08:00 时区信息
```

### 发送消息时的时间戳

在 `customer_syncer.py` 的 `_store_sent_message` 方法中：

```python
from zoneinfo import ZoneInfo

tz = ZoneInfo("Asia/Shanghai")
now = datetime.now(tz)  # ✅ 已修复：带时区
timestamp_parsed = now  # 格式: 2025-12-28 17:40:00+08:00
```

**状态：** ✅ 已修复，现在统一使用带时区的时间戳格式

## 总结

| 格式                         | 时区信息       | 推荐度     | 用途               |
| ---------------------------- | -------------- | ---------- | ------------------ |
| `2025-12-28 17:40:00+08:00`  | ✅ 有 (+08:00) | ⭐⭐⭐⭐⭐ | 数据库存储（推荐） |
| `2026-01-01 14:14:51.467187` | ❌ 无          | ⚠️ 不推荐  | 临时时间戳         |

**最佳实践：**

- ✅ 统一使用带时区的时间戳格式
- ✅ 所有时间戳都使用 `ZoneInfo("Asia/Shanghai")`
- ✅ 确保 `timestamp_parsed` 字段在数据库中格式一致

## 相关代码位置

1. **时间戳解析**: `src/wecom_automation/services/timestamp_parser.py`
2. **消息存储**: `src/wecom_automation/services/sync/customer_syncer.py` → `_store_sent_message`
3. **数据库模型**: `src/wecom_automation/database/models.py` → `MessageRecord`
