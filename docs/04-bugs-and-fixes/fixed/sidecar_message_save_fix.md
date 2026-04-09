# Sidecar 多条消息只保存第一条的 Bug 修复

## 问题描述

在 Sidecar 模式下发送多条消息时，只有第一条消息能存入数据库并显示在面板中，后续发送的消息无法保存到数据库。

## 问题分析

### 根本原因

在 `wecom-desktop/backend/routers/sidecar.py` 的 `send_and_save_message` 端点中，INSERT 语句**缺少必需的 `message_hash` 字段**。

```python
# 问题代码（第 506-527 行）
cursor.execute(
    """
    INSERT INTO messages (
        customer_id,
        content,
        message_type,
        is_from_kefu,
        timestamp_raw,
        timestamp_parsed,
        created_at
    ) VALUES (?, ?, 'text', 1, ?, ?, ?)
    """,
    ...
)
```

### 数据库约束

在 `messages` 表的 schema 中，`message_hash` 字段被定义为：

```sql
message_hash TEXT UNIQUE NOT NULL,  -- SHA256 hash for deduplication
```

- `NOT NULL`：字段不能为空
- `UNIQUE`：值必须唯一

### 为什么第一条能保存？

实际上第一条消息也**没有**保存成功。问题是：

1. INSERT 语句缺少 `message_hash` 字段，违反 `NOT NULL` 约束
2. 数据库抛出异常
3. 异常被 `except Exception as e` 捕获并静默处理（只打印日志）
4. 函数返回 `success=True` 但 `message_saved=False`

用户可能误以为第一条消息保存成功，但实际上每次发送都失败了。

### 为什么错误被静默处理？

代码设计意图是：即使消息无法保存到数据库，发送操作本身成功就返回成功。这导致数据库保存错误被隐藏。

```python
except Exception as e:
    # Log but don't fail - message was sent successfully
    print(f"Failed to save message to database: {e}")
```

## 解决方案

### 修改的文件

**`wecom-desktop/backend/routers/sidecar.py`**

1. **在文件顶部添加 hashlib 导入**：

   ```python
   import hashlib
   ```

2. **在 INSERT 语句前生成唯一的 message_hash**：

   ```python
   # Generate unique message hash for deduplication
   # Use UUID + timestamp to ensure uniqueness for sidecar messages
   hash_source = f"sidecar_{serial}_{now.isoformat()}_{uuid.uuid4()}"
   message_hash = hashlib.sha256(hash_source.encode()).hexdigest()
   ```

3. **在 INSERT 语句中添加 message_hash 字段**：
   ```python
   cursor.execute(
       """
       INSERT INTO messages (
           customer_id,
           content,
           message_type,
           is_from_kefu,
           timestamp_raw,
           timestamp_parsed,
           message_hash,
           created_at
       ) VALUES (?, ?, 'text', 1, ?, ?, ?, ?)
       """,
       (
           customer_id,
           message,
           now.strftime("%H:%M"),
           now.isoformat(),
           message_hash,
           now.isoformat(),
       )
   )
   ```

### message_hash 生成策略

使用 `sidecar_{serial}_{timestamp}_{uuid}` 格式确保：

- `serial`：设备标识
- `timestamp`：发送时间（毫秒精度）
- `uuid`：随机 UUID 确保绝对唯一性

这样即使在同一秒内发送多条消息，每条消息也会有唯一的 hash。

## 效果

修复后：

- 每条通过 Sidecar 发送的消息都能正确保存到数据库
- 消息能在历史记录面板中显示
- 多条快速发送的消息不会相互冲突

## 相关文件

- `wecom-desktop/backend/routers/sidecar.py` - send-and-save 端点
- `src/wecom_automation/database/schema.py` - 数据库 schema 定义
