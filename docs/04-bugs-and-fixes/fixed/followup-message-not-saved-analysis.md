# Followup 消息写入数据库失败问题分析

## 问题描述

- **现象**：测试脚本 `test_followup_phase2_db_write.py` 可以成功写入数据库
- **实际情况**：程序运行时日志显示 "have saved" 但数据库中没有对应数据
- **影响范围**：`followup/scanner.py` 中的 `_save_kefu_message_via_handler()` 方法

---

## ✅ 已确认的根因

### 🔴 数据库路径不一致（已确认）

**问题**：存在两个独立的数据库文件，程序写入了错误的位置

| 数据库文件                                                          | 大小  | 说明                |
| ------------------------------------------------------------------- | ----- | ------------------- |
| `d:\111\android_run_test-main\wecom_conversations.db`               | 651KB | ✅ 正确的主数据库   |
| `d:\111\android_run_test-main\wecom-desktop\wecom_conversations.db` | 122KB | ❌ 程序错误写入此处 |

**原因**：当从 `wecom-desktop/backend` 目录运行时，`schema.py` 的路径解析逻辑会在当前工作目录创建/使用数据库文件。

---

## 问题根因分析（其他潜在问题）

### 🔴 根因 1：Customer ID 不一致（最可能的原因）

**两个 Repository 使用不同的 Customer 查找/创建逻辑：**

#### FollowUpRepository (`wecom-desktop/backend/servic../03-impl-and-arch/repository.py`)

```python
# 第 252 行 - 只按 name 查找
cursor.execute("SELECT id FROM customers WHERE name = ?", (name,))
```

#### ConversationRepository (`src/wecom_automation/database/repository.py`)

```python
# 第 351-360 行 - 按 name + kefu_id + channel 查找
if channel:
    cursor.execute(
        "SELECT * FROM customers WHERE name = ? AND kefu_id = ? AND channel = ?",
        (name, kefu_id, channel)
    )
else:
    cursor.execute(
        "SELECT * FROM customers WHERE name = ? AND kefu_id = ? AND channel IS NULL",
        (name,)
    )
```

**后果**：

- `FollowUpScanner` 通过 `FollowUpRepository.find_or_create_customer()` 获取 `customer_id`
- 然后将这个 `customer_id` 传给 `TextMessageHandler`
- 但 `TextMessageHandler` 使用 `ConversationRepository`，可能找不到对应的客户记录
- 导致消息被保存到一个"幽灵"客户下，或者外键约束失败

---

### 🔴 根因 2：Customers 表结构差异

#### FollowUpRepository 创建的表 (第 54-65 行)

```sql
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel TEXT,
    kefu_id INTEGER,  -- 可以为 NULL
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (kefu_id) REFERENCES kefus(id)
)
-- 注意：没有 UNIQUE 约束
```

#### ConversationRepository 使用的 schema (schema.py 第 61-71 行)

```sql
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel TEXT,
    kefu_id INTEGER NOT NULL REFERENCES kefus(id) ON DELETE CASCADE,  -- 不能为 NULL
    last_message_preview TEXT,
    last_message_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, channel, kefu_id)  -- 有 UNIQUE 约束
)
```

**后果**：

- 同一个客户名可能在两种创建逻辑下产生不同的 ID
- 外键约束可能导致静默失败

---

### 🔴 根因 3：SQLite WAL 模式问题

SQLite 的 Write-Ahead Logging (WAL) 模式下：

- 写入操作先进入 `.db-wal` 文件
- 需要 checkpoint 才会写入主数据库文件
- 如果程序异常退出或连接未正常关闭，数据可能丢失

**检查方法**：

```bash
# 查看是否存在 WAL 文件
dir wecom_conversations.db*
```

如果存在 `wecom_conversations.db-wal` 和 `wecom_conversations.db-shm`，说明有未 checkpoint 的数据。

---

### 🟡 根因 4：数据库路径不一致

#### 路径定义对比

| 组件                                   | 路径计算方式                                                            | 实际路径                                              |
| -------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------- |
| `followup/service.py`                  | `Path(__file__).parent.parent.parent.parent / "wecom_conversations.db"` | `d:\111\android_run_test-main\wecom_conversations.db` |
| `schema.py` (`ConversationRepository`) | 智能解析：先检查 CWD，再用 PROJECT_ROOT                                 | 取决于运行目录                                        |

**风险**：如果从 `wecom-desktop/backend` 目录运行，`schema.py` 的路径解析可能与 `followup/service.py` 不同。

---

### 🟡 根因 5：消息重复检测导致跳过

`ConversationRepository.add_message_if_not_exists()` 使用消息哈希去重：

```python
# MessageRecord.compute_hash() 计算基于：
# - customer_id
# - content
# - message_type
# - is_from_kefu
# - timestamp_raw
```

如果相同内容在短时间内被多次发送（比如测试），可能被判定为重复而跳过。

---

## 流程追踪

### 实际执行流程 (`_send_followup_message` 方法)

```
1. FollowUpRepository.find_or_create_customer(user_name, user_channel, serial)
   └── 返回 customer_id = X (基于 name 查找)

2. FollowUpRepository.record_attempt(customer_id=X, ...)
   └── 写入 followup_attempts 表 ✅

3. _save_kefu_message_via_handler(customer_id=X, ...)
   └── TextMessageHandler.process(message, context)
       └── MessageRecord(customer_id=X, ...)  # 使用传入的 customer_id
       └── ConversationRepository.add_message_if_not_exists(record)
           └── 检查哈希是否存在
           └── 如果不存在，执行 INSERT
           └── ⚠️ 可能因外键约束失败（customer_id=X 在 ConversationRepository 视角下可能不存在）
```

### 问题关键点

`scanner.py` 第 524-532 行：

```python
# 2. 使用 TextMessageHandler 保存消息（复用全量同步的方法）
try:
    await self._save_kefu_message_via_handler(
        message_content=final_message,
        customer_id=customer_id,    # ⚠️ 这个 ID 来自 FollowUpRepository
        customer_name=user_name,
        channel=user_channel,
        device_serial=serial,
    )
except Exception as db_err:
    # ⚠️ 异常被捕获但没有打断流程
    self._logger.error(f"[{serial}]   ❌ Failed to save message to DB: {db_err}")
```

---

## 解决方案

### 方案 1：统一使用 ConversationRepository（推荐）

修改 `FollowUpScanner` 完全使用 `ConversationRepository` 来查找/创建客户：

```python
# scanner.py 中修改 _send_followup_message

# 原来：
customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)

# 修改为：
# 1. 先获取/创建设备
device = self._conversation_repo.get_or_create_device(serial)

# 2. 获取/创建客服（使用固定名称）
kefu = self._conversation_repo.get_or_create_kefu("kefu", device.id)

# 3. 获取/创建客户
customer = self._conversation_repo.get_or_create_customer(
    name=user_name,
    kefu_id=kefu.id,
    channel=user_channel
)
customer_id = customer.id
```

### 方案 2：在 FollowUpRepository 中同步创建 ConversationRepository 兼容的记录

```python
# followup/repository.py 中修改 find_or_create_customer

def find_or_create_customer(
    self,
    name: str,
    channel: Optional[str] = None,
    device_serial: Optional[str] = None
) -> int:
    with self._connection() as conn:
        cursor = conn.cursor()

        # 先查找/创建设备
        if device_serial:
            cursor.execute("SELECT id FROM devices WHERE serial = ?", (device_serial,))
            device_row = cursor.fetchone()
            if not device_row:
                cursor.execute(
                    "INSERT INTO devices (serial) VALUES (?)", (device_serial,)
                )
                device_id = cursor.lastrowid
            else:
                device_id = device_row[0]

        # 查找/创建客服
        kefu_name = "kefu"
        cursor.execute("SELECT id FROM kefus WHERE name = ?", (kefu_name,))
        kefu_row = cursor.fetchone()
        if not kefu_row:
            cursor.execute(
                "INSERT INTO kefus (name, department) VALUES (?, ?)",
                (kefu_name, None)
            )
            kefu_id = cursor.lastrowid
        else:
            kefu_id = kefu_row[0]

        # 按 ConversationRepository 的逻辑查找客户
        if channel:
            cursor.execute(
                "SELECT id FROM customers WHERE name = ? AND kefu_id = ? AND channel = ?",
                (name, kefu_id, channel)
            )
        else:
            cursor.execute(
                "SELECT id FROM customers WHERE name = ? AND kefu_id = ? AND channel IS NULL",
                (name, kefu_id)
            )

        row = cursor.fetchone()
        if row:
            return row[0]

        # 创建新客户（符合 ConversationRepository schema）
        cursor.execute("""
            INSERT INTO customers (name, channel, kefu_id)
            VALUES (?, ?, ?)
        """, (name, channel, kefu_id))
        conn.commit()
        return cursor.lastrowid
```

### 方案 3：强制 Checkpoint WAL（如果是 WAL 模式问题）

在关键写入后强制 checkpoint：

```python
def force_checkpoint(self):
    with self._connection() as conn:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
```

---

## 诊断步骤

### 步骤 1：检查数据库文件

```powershell
# 检查是否有 WAL 文件
dir d:\111\android_run_test-main\wecom_conversations.db*
```

### 步骤 2：确认数据库路径

在程序启动时添加日志：

```python
# scanner.py 初始化时
self._logger.info(f"FollowUpRepository db_path: {self._repository._db_path}")
self._logger.info(f"ConversationRepository db_path: {self._conversation_repo.db_path}")
```

### 步骤 3：检查 Customer ID 一致性

```sql
-- 查看 customers 表结构
PRAGMA table_info(customers);

-- 查看 FollowUpRepository 创建的客户
SELECT id, name, channel, kefu_id FROM customers WHERE name = '测试客户名';

-- 检查是否有孤立的 customer_id
SELECT DISTINCT customer_id FROM messages
WHERE customer_id NOT IN (SELECT id FROM customers);
```

### 步骤 4：启用详细日志

```python
# 在 TextMessageHandler.process() 中添加
self._logger.info(f"Saving message: customer_id={context.customer_id}, hash={record.message_hash[:16]}")

# 在 ConversationRepository.add_message_if_not_exists() 中添加
if not added:
    logger.info(f"Message skipped (duplicate): hash={msg_hash}")
else:
    logger.info(f"Message created: id={created.id}, hash={msg_hash[:16]}")
```

---

## 快速修复（临时方案）

如果需要立即修复，可以在 `_save_kefu_message_via_handler` 中绕过 `TextMessageHandler`，直接使用 SQL：

```python
async def _save_kefu_message_via_handler(self, ...):
    import hashlib

    # 生成消息哈希
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    timestamp_raw = now.strftime("%H:%M")

    hash_content = f"{customer_id}:{message_content}:text:True:{timestamp_raw}"
    message_hash = hashlib.sha256(hash_content.encode()).hexdigest()

    # 直接写入
    with self._repository._connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO messages
                (customer_id, content, message_type, is_from_kefu,
                 timestamp_raw, timestamp_parsed, message_hash, created_at)
                VALUES (?, ?, 'text', 1, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                customer_id,
                message_content,
                timestamp_raw,
                now.isoformat(),
                message_hash
            ))
            conn.commit()
            self._logger.info(f"Message saved directly: id={cursor.lastrowid}")
            return MessageProcessResult(added=True, message_type="text", message_id=cursor.lastrowid)
        except Exception as e:
            self._logger.error(f"Direct save failed: {e}")
            return MessageProcessResult(added=False, message_type="text")
```

---

## 总结

| 问题               | 可能性 | 影响                    | 修复难度 |
| ------------------ | ------ | ----------------------- | -------- |
| Customer ID 不一致 | 🔴 高  | 消息保存到错误客户/失败 | 中等     |
| 表结构差异         | 🟡 中  | 外键约束失败            | 较高     |
| WAL 模式           | 🟡 中  | 数据在缓存中未持久化    | 低       |
| 路径不一致         | 🟡 中  | 写入不同数据库文件      | 低       |
| 重复检测           | 🟢 低  | 相同消息被跳过          | 低       |

**建议优先级**：

1. ✅ 首先检查日志中的数据库路径是否一致
2. ✅ 然后检查 Customer ID 在两个 Repository 中是否一致
3. ✅ 最后检查 WAL 文件是否存在

---

## 参考文件

- `wecom-desktop/backend/servic../03-impl-and-arch/scanner.py` - 第 524-532 行
- `wecom-desktop/backend/servic../03-impl-and-arch/repository.py` - 第 241-280 行
- `src/wecom_automation/database/repository.py` - 第 386-418 行
- `src/wecom_automation/database/schema.py` - 第 184-211 行

---

## ✅ 修复记录

### 2026-01-01: 确认根因

**问题确认**：数据库路径不一致

- 程序写入：`wecom-desktop/wecom_conversations.db`
- 应该使用：`android_run_test-main/wecom_conversations.db`（项目根目录）

### ✅ 修复已完成

#### 1. 修复路径计算错误

以下文件的 `PROJECT_ROOT` 计算从 4 个 parent 改为 5 个 parent：

| 文件                                                         | 修改前                         | 修改后                                |
| ------------------------------------------------------------ | ------------------------------ | ------------------------------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/service.py` | `.parent.parent.parent.parent` | `.parent.parent.parent.parent.parent` |
| `wecom-desktop/backend/routers/followup.py`                  | `.parent.parent.parent.parent` | `.parent.parent.parent.parent.parent` |
| `wecom-desktop/backend/services/followup_service_backup.py`  | `.parent.parent.parent.parent` | `.parent.parent.parent.parent.parent` |

#### 2. 删除错误的数据库文件

- ✅ 已删除 `wecom-desktop/wecom_conversations.db`
- 程序现在会使用正确的数据库：`android_run_test-main/wecom_conversations.db`
