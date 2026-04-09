# Follow-up 系统多项改进：时区处理、提示词简化、表结构兼容

**日期**: 2026-02-03
**状态**: ✅ 已修复
**修改类型**: Bug修复 + 优化

---

## 修改概述

本次修改包含三项独立但相关的改进：

### 1. 修复时区处理错误导致的类型不匹配

### 2. 简化 AI 提示词结构

### 3. 改进数据库表结构兼容性检查

---

## 问题 1: 时区处理错误

### 问题描述

`FollowupQueueManager.process_conversations()` 在计算空闲时间时出现类型错误：

```python
time_since = now - conv.last_message_time
# TypeError: can't subtract offset-naive and offset-aware datetimes
```

### 根本原因

- `now` 是 `datetime.now()` 返回的 offset-naive datetime 对象（无时区信息）
- `conv.last_message_time` 可能是 offset-aware datetime 对象（有时区信息）
- Python 不允许直接对两种类型进行减法运算

### 修复方案

在 `queue_manager.py` 的 `process_conversations()` 方法中统一时区处理：

```python
# 统一时区处理：将 offset-aware 转为 offset-naive
last_msg_time = conv.last_message_time
if hasattr(last_msg_time, 'tzinfo') and last_msg_time.tzinfo is not None:
    # 转换为本地时间并移除时区信息
    last_msg_time = last_msg_time.replace(tzinfo=None)

time_since = now - last_msg_time
```

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/queue_manager.py`

---

## 问题 2: AI 提示词过于冗长

### 问题描述

`response_detector.py` 中的 AI 提示词包含大量冗余的 XML 标签结构：

- `<requirements>` (functional, content_rules)
- `<thinking>` (多步骤思考流程)
- `<output_format>` (重复的输出说明)

这些标签：

1. 增加了 token 消耗
2. 对 AI 模型未必有帮助（现代模型更偏好简洁的指令）
3. 与已有的 `<system_prompt>` 和 `<constraints>` 功能重复

### 修复方案

移除冗余标签，保留核心指令：

**移除的内容**:

- `<requirements>` 整个标签（function 和 content_rules 已隐含在 system_prompt 中）
- `<thinking>` 标签（现代模型不需要显式的思考步骤）
- `<output_format>` 标签（与最后的指令重复）

**保留的内容**:

- `<system_prompt>` - 核心角色和风格定义
- `<constraints>` - 长度限制、禁止模式、特殊命令

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

### 对比

**修复前** (~200 tokens):

```xml
<system_prompt>...</system_prompt>

<requirements>
<functional>1. 生成一条自然的跟进消息...</functional>
<content_rules>1. 不要重复之前...</content_rules>
</requirements>

<constraints>
<length_limit>消息控制在 50 字以内</length_limit>
<forbidden_patterns>1. 禁止使用"打扰了"...</forbidden_patterns>
<special_commands>如果判断客户明确...</special_commands>
</constraints>

<thinking>
在生成消息之前，请按以下步骤思考：
1. 回顾对话历史...
2. 分析客户最后一条消息...
...
</thinking>

<output_format>
直接输出跟进消息文本，不要包含任何解释...
</output_format>
```

**修复后** (~80 tokens):

```xml
<system_prompt>...</system_prompt>

<constraints>
<length_limit>消息控制在 50 字以内</length_limit>
<forbidden_patterns>1. 禁止使用"打扰了"等负面开场...</forbidden_patterns>
<special_commands>如果判断客户明确表示不感兴趣或要求转人工，直接返回: command back to user operation</special_commands>
</constraints>
```

---

## 问题 3: 数据库表结构兼容性

### 问题描述

`followup_manage.py` 在初始化表结构时假设表总是具有最新的列结构，但如果数据库中存在旧版本的表（例如从之前的代码版本创建），会导致索引创建失败或查询错误。

### 根本原因

代码直接创建索引而不检查表是否具有正确的列：

```python
# 旧代码 - 假设表总是正确的
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_followup_attempts_device_status
    ON followup_attempts(device_serial, status)  # 如果 device_serial 列不存在会失败
""")
```

### 修复方案

在创建索引前先检查表结构：

```python
# 检查表是否有正确的列结构
cursor.execute("PRAGMA table_info(followup_attempts)")
columns = {row[1] for row in cursor.fetchall()}

# 只有当表有正确的列时才创建索引
if "device_serial" in columns and "status" in columns:
    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_followup_attempts_device_status
            ON followup_attempts(device_serial, status)
        """)
    except sqlite3.OperationalError as e:
        logging.warning(f"Failed to create device_status index: {e}")
else:
    logging.warning(
        "followup_attempts table has old structure, some features may not work. "
        "Consider deleting the old table to let the system recreate it."
    )
```

**优点**:

- 对旧表结构更宽容
- 提供有用的警告信息
- 不会因为索引失败导致整个初始化崩溃

**文件**: `wecom-desktop/backend/routers/followup_manage.py`

---

## 影响范围

| 组件         | 影响                                     |
| ------------ | ---------------------------------------- |
| 补刀队列管理 | 修复时区计算错误，确保空闲时间判断准确   |
| AI 回复生成  | 减少 token 消耗，提升响应速度            |
| 数据库初始化 | 更好的向后兼容性，减少因表结构导致的错误 |

---

## 验证方法

### 时区修复验证

1. 在不同时区的设备上运行 Follow-up
2. 确认空闲时间计算正确
3. 检查日志中的"空闲时长: X 分钟"是否合理

### AI 提示词验证

1. 触发补刀和实时回复
2. 检查生成的消息质量是否下降（应该保持一致或更好）
3. 对比 AI API 调用的 token 使用量（应该减少）

### 表结构兼容性验证

1. 在有旧表结构的数据库上启动后端
2. 确认不会因为索引创建失败而崩溃
3. 检查日志中的警告信息

---

## 相关文件

| 文件                                                                   | 修改类型 |
| ---------------------------------------------------------------------- | -------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/queue_manager.py`     | Bug修复  |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 优化     |
| `wecom-desktop/backend/routers/followup_manage.py`                     | 增强     |
| `settings/ai_config.json`                                              | 自动更新 |
| `wecom_conversations.db`                                               | 数据更新 |
