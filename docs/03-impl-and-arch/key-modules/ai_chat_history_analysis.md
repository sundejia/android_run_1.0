# AI聊天记录拼接分析报告

## 概述

本文档详细分析了WeCom自动化框架中，如何为AI回复拼接聊天记录，包括数据来源、拼接逻辑、以及完整的数据流。

---

## 1. 数据来源

### 1.1 主要数据源：SQLite数据库

**数据库位置**：

- 默认路径：`wecom_conversations.db`（项目根目录）
- 可通过环境变量 `WECOM_DB_PATH` 自定义
- 代码位置：`src/wecom_automation/database/schema.py`

**核心数据表**：

```sql
-- 消息表（主要数据源）
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,        -- 关联客户
    content TEXT,                        -- 消息内容
    message_type TEXT NOT NULL,          -- 消息类型: text, image, voice, video等
    is_from_kefu BOOLEAN NOT NULL,       -- 是否为客服发送 (1=客服, 0=客户)
    timestamp_raw TEXT,                  -- 原始时间戳 (如 "14:30")
    timestamp_parsed TEXT,               -- 解析后的时间戳 (ISO格式)
    extra_info TEXT,                     -- 额外信息
    message_hash TEXT,                   -- 消息哈希（用于去重）
    ui_position INTEGER,                 -- UI中的显示位置
    created_at TEXT NOT NULL             -- 记录创建时间
);

-- 客户表
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kefu_id INTEGER NOT NULL,            -- 关联的客服
    name TEXT NOT NULL,                  -- 客户名称
    channel TEXT,                        -- 渠道信息
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 客服表（kefus）
CREATE TABLE kefus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                  -- 客服名称
    department TEXT,                     -- 部门
    verification_status TEXT,            -- 认证状态
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 1.2 消息采集来源

**采集时机**：

1. **初始同步（Initial Sync）**：
   - 脚本：`initial_sync.py`, `initial_sync_v2.py`
   - 扫描企业微信消息列表，提取所有对话
   - 代码：`src/wecom_automation/services/sync/customer_syncer.py`

2. **交互式同步（Interactive Sync）**：
   - 在同步过程中发送测试消息并等待回复
   - 实时检测新消息并存入数据库

3. **Sidecar实时同步**：
   - 通过Sidecar界面实时监控对话
   - 发送消息后立即保存到数据库
   - 端点：`POST /a../03-impl-and-arch/{serial}/send-and-save`

---

## 2. 聊天记录查询逻辑

### 2.1 数据库查询（Repository层）

**代码位置**：`src/wecom_automation/database/repository.py:746-777`

```python
def get_recent_messages_for_customer(
    self,
    customer_id: int,
    limit: int = 10,
) -> List[MessageRecord]:
    """
    获取最近N条消息用于AI上下文

    消息按时间排序（最旧的在前）以保持对话流程
    """
    query = """
        SELECT * FROM (
            SELECT * FROM messages
            WHERE customer_id = ?
            ORDER BY COALESCE(ui_position, id) DESC
            LIMIT ?
        ) subquery
        ORDER BY COALESCE(ui_position, id) ASC
    """
    cursor.execute(query, (customer_id, limit))
    return [MessageRecord.from_row(row) for row in cursor.fetchall()]
```

**关键点**：

- 使用子查询先获取最新的N条消息
- 然后按 `ui_position` 或 `id` 升序排列（旧的在前）
- 保证对话的时间顺序正确

### 2.2 调用链路

```
CustomerSyncer.sync()
  └─> _send_reply_to_customer()
       └─> _get_conversation_history(customer_id, limit=10)
            └─> repository.get_recent_messages_for_customer(customer_id, limit)
```

**代码位置**：`src/wecom_automation/services/sync/customer_syncer.py:692-703`

```python
def _get_conversation_history(self, customer_id: int, limit: int = 10) -> List[dict]:
    """获取会话历史用于AI上下文"""
    try:
        messages = self._repository.get_messages_for_customer(customer_id)
        recent = messages[-limit:] if len(messages) > limit else messages
        return [
            {"content": m.content, "is_from_kefu": m.is_from_kefu}
            for m in recent
            if m.content
        ]
    except Exception:
        return []
```

---

## 3. 聊天记录拼接逻辑

### 3.1 AI服务接口

**代码位置**：`src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py:101-179`

```python
async def get_reply(
    self,
    message: str,                        # 当前客户消息
    context: MessageContext,             # 消息上下文
    history: Optional[List[Dict[str, Any]]] = None  # 历史消息
) -> Optional[str]:
    """
    获取AI回复

    Args:
        message: 用户消息
        context: 消息上下文（包含customer_id, customer_name, device_serial等）
        history: 历史消息列表（从数据库查询）

    Returns:
        AI生成的回复，失败返回None
    """
```

### 3.2 历史消息格式化

**代码位置**：`src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py:235-285`

```python
def _format_conversation_context(
    self,
    history: List[Dict[str, Any]],      # 历史消息
    current_message: str,                # 当前消息
    max_length: int = 800                # 最大长度限制
) -> str:
    """
    格式化会话上下文

    将历史消息拼接成以下格式：
    [CONTEXT]
    AGENT: <客服消息1>
    STREAMER: <客户消息1>
    AGENT: <客服消息2>
    STREAMER: <客户消息2>

    [LATEST MESSAGE]
    <当前客户消息>
    """
    context_lines = []
    for msg in history:
        content = msg.get("content", "")
        is_from_kefu = msg.get("is_from_kefu", False)

        if not content or not content.strip():
            continue

        role = "AGENT" if is_from_kefu else "STREAMER"
        context_lines.append(f"{role}: {content}")

    # 构建最新消息部分
    latest_part = f"[LATEST MESSAGE]\n{current_message}"

    if not context_lines:
        return latest_part

    # 逐步减少上下文直到符合长度限制
    while context_lines:
        parts = ["[CONTEXT]"]
        parts.extend(context_lines)
        parts.append("")
        parts.append(latest_part)

        formatted = "\n".join(parts)

        if len(formatted) <= max_length:
            return formatted

        # 移除最旧的消息
        context_lines.pop(0)

    return latest_part
```

### 3.3 最终拼接结果示例

```
system_prompt: If the user wants to switch to human operation, human agent, or manual service, directly return ONLY the text 'command back to user operation' without any other text.

user_prompt: [CONTEXT]
AGENT: 您好，请问有什么可以帮助您的？
STREAMER: 我想了解一下产品价格
AGENT: 我们的产品价格在100-500元之间
STREAMER: 好的，谢谢

[LATEST MESSAGE]
收到您的消息: 好的，谢谢...
```

---

## 4. 完整数据流

### 4.1 消息采集流程

```
┌─────────────────┐
│  Android Device │
│   (WeCom App)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  ADBService (DroidRun)                  │
│  - get_ui_tree()                        │
│  - get_clickable_elements()             │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  UIParserService                        │
│  - extract_conversation_messages()      │
│  - parse message content/timestamp      │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  MessageProcessor                       │
│  - process() each message               │
│  - handlers: text, image, voice, video  │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  ConversationRepository                 │
│  - add_message_if_not_exists()          │
│  - save to SQLite DB                    │
└─────────────────────────────────────────┘
```

### 4.2 AI回复生成流程

```
┌─────────────────────────────────────────┐
│  CustomerSyncer.sync()                  │
│  - 正在同步客户对话                      │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  _send_reply_to_customer()              │
│  - 检测到客户消息需要回复                │
└────────┬────────────────────────────────┘
         │
         ├─────────────────┬─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ _get_        │  │ AIReply      │  │ Sidecar/     │
│ conversation │  │ Service.     │  │ WeCom.send   │
│ _history()   │  │ get_reply()  │  │              │
└──────┬───────┘  └──────┬───────┘  └──────────────┘
       │                 │
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ Repository.  │  │ Format:      │
│ get_recent_  │  │ [CONTEXT]    │
│ messages()   │  │ AGENT: ...   │
│              │  │ STREAMER: ...│
│ SQLite DB    │  │ [LATEST]    │
└──────┬───────┘  └──────┬───────┘
       │                 │
       └─────────┬───────┘
                 ▼
        ┌──────────────────┐
        │ POST to AI Server│
        │ /chat endpoint   │
        └──────────────────┘
```

---

## 5. 关键特性

### 5.1 消息去重

**机制**：使用 `message_hash` 字段

- 源数据：内容、时间戳、发送方
- 哈希算法：SHA256
- 查询时自动过滤重复消息

### 5.2 上下文长度控制

**策略**：

- 默认最大长度：800字符
- 自动裁剪：从最旧的消息开始移除
- 保留最新消息优先

### 5.3 角色识别

**标记逻辑**：

- `is_from_kefu = 1` → AGENT（客服）
- `is_from_kefu = 0` → STREAMER（客户/主播）

### 5.4 多设备支持

- 每个设备独立端口（8080, 8081, 8082...）
- 客服关联到设备（kefu_devices表）
- 客户关联到客服（customers.kefu_id）

---

## 6. API端点

### 6.1 Sidecar聊天历史查询

**端点**：`GET /a../03-impl-and-arch/{serial}/conversation-history`

**参数**：

- `serial`: 设备序列号
- `contact_name`: 客户名称
- `channel`: 渠道（可选）
- `limit`: 最大消息数（默认100）

**响应**：

```json
{
  "success": true,
  "customer_id": 123,
  "customer_name": "张三",
  "channel": "微信",
  "kefu_name": "客服小王",
  "messages": [
    {
      "id": 456,
      "content": "您好",
      "message_type": "text",
      "is_from_kefu": true,
      "timestamp_raw": "14:30",
      "timestamp_parsed": "2025-12-28T14:30:00+08:00",
      "created_at": "2025-12-28T14:30:00+08:00"
    }
  ],
  "total_messages": 50
}
```

**代码位置**：`wecom-desktop/backend/routers/sidecar.py:628-799`

---

## 7. 相关文件索引

| 文件路径                                                                      | 功能说明                 |
| ----------------------------------------------------------------------------- | ------------------------ |
| `src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py` | AI回复服务，核心拼接逻辑 |
| `src/wecom_automation/services/sync/customer_syncer.py`                       | 客户同步器，调用AI回复   |
| `src/wecom_automation/database/repository.py`                                 | 数据库仓库，查询历史消息 |
| `src/wecom_automation/database/schema.py`                                     | 数据库schema定义         |
| `wecom-desktop/backend/routers/sidecar.py`                                    | Sidecar API端点          |
| `initial_sync.py`                                                             | 初始同步脚本             |
| `initial_sync_v2.py`                                                          | V2版本同步脚本           |

---

## 8. 总结

### 数据流总结

```
数据库 (messages表)
    ↓
repository.get_recent_messages_for_customer()
    ↓
CustomerSyncer._get_conversation_history()
    ↓
AIReplyService._format_conversation_context()
    ↓
格式化为 [CONTEXT] + [LATEST MESSAGE]
    ↓
发送到AI服务器 /chat 端点
```

### 核心逻辑

1. **数据来源**：从SQLite数据库的 `messages` 表查询
2. **查询条件**：按 `customer_id` 筛选，按 `ui_position/id` 排序
3. **数量限制**：默认最近10条消息
4. **拼接格式**：`[CONTEXT]\nAGENT: ...\nSTREAMER: ...\n\n[LATEST MESSAGE]\n...`
5. **长度控制**：800字符限制，自动裁剪
6. **角色标记**：AGENT（客服）和 STREAMER（客户）

---

_生成时间：2025-01-21_
_分析版本：v2a5f-ai_
