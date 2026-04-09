# AI Reply 上下文不足问题分析

> 文档创建于：2026-01-20  
> 版本：v1.1  
> 状态：待修复  
> 关联：[docs/ai_prompt_context_logic.md](../ai_prompt_context_logic.md)

## 目录

1. [问题描述](#问题描述)
2. [Sync 流程分析](#sync-流程分析)
3. [FollowUp 流程分析](#followup-流程分析)
4. [问题对比总结](#问题对比总结)
5. [修复方案](#修复方案)
6. [实现细节](#实现细节)
7. [测试验证](#测试验证)

---

## 问题描述

### 现象

当使用**后端 AI Reply（自动回复）**功能时，生成的回复质量不如**前端 Generate 按钮**生成的回复。

| 功能                 | 回复质量    | 备注                     |
| -------------------- | ----------- | ------------------------ |
| **Generate 按钮**    | ✅ 比较准确 | 用户手动触发，上下文完整 |
| **AI Reply（自动）** | ❌ 不够准确 | 后端自动触发，上下文不足 |

### 用户反馈

> "只从当前聊天页面作为上下文不够，generate 按钮生成的比较准确"

---

## Sync 流程分析

### 代码位置

**文件**：`src/wecom_automation/services/sync/customer_syncer.py`

### 关键发现：✅ Sync 流程已正确使用数据库历史！

在 `CustomerSyncer._send_reply_to_customer()` 方法（第 437-506 行）中：

```python
# 第 473-477 行
if self._ai_service:
    history = self._get_conversation_history(customer.id)  # ✅ 从数据库获取
    try:
        ai_reply = await self._ai_service.get_reply(message_content, context, history)
```

`_get_conversation_history()` 方法（第 692-703 行）：

```python
def _get_conversation_history(self, customer_id: int, limit: int = 10) -> List[dict]:
    """获取会话历史用于AI上下文"""
    try:
        messages = self._repository.get_messages_for_customer(customer_id)  # ← 从数据库读取
        recent = messages[-limit:] if len(messages) > limit else messages
        return [
            {"content": m.content, "is_from_kefu": m.is_from_kefu}
            for m in recent
            if m.content
        ]
    except Exception:
        return []
```

### Sync 流程的上下文来源

| 特性             | 值                        |
| ---------------- | ------------------------- |
| **数据来源**     | 📊 数据库 `messages` 表   |
| **消息数量**     | 最近 **10 条**            |
| **是否包含历史** | ✅ 包含所有历史同步的消息 |
| **上下文完整性** | ✅ 完整                   |

### Sync 流程数据流

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Sync 流程 - 上下文完整 ✅                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  _send_reply_to_customer()                                                  │
│         │                                                                   │
│         │  history = self._get_conversation_history(customer.id)            │
│         ▼                                                                   │
│  self._repository.get_messages_for_customer(customer_id)                    │
│         │                                                                   │
│         │  SELECT * FROM messages WHERE customer_id = ?                     │
│         ▼                                                                   │
│  数据库返回所有历史消息                                                      │
│         │                                                                   │
│         │  messages[-10:] 取最近 10 条                                       │
│         ▼                                                                   │
│  AI 服务收到 10 条完整历史消息                                               │
│         │                                                                   │
│         ▼                                                                   │
│  ✅ AI 能看到完整的对话脉络，生成准确回复                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 结论：Sync 流程无需修改

Sync 流程（`customer_syncer.py`）已正确从数据库读取历史消息，上下文完整性与前端 Generate 按钮一致。

---

## FollowUp 流程分析

### 代码位置

| 文件                                                     | 描述                                      |
| -------------------------------------------------------- | ----------------------------------------- |
| `backend/servic../03-impl-and-arch/response_detector.py` | 响应检测器 - 检测红点并自动回复           |
| `backend/servic../03-impl-and-arch/scanner.py`           | 补刀扫描器 - 对客服最后发送的用户进行补刀 |

### 关键发现：❌ FollowUp 流程只使用 UI 提取的消息！

#### response_detector.py 问题

在 `_generate_reply()` 方法（第 756-875 行）中：

```python
async def _generate_reply(
    self,
    user_name: str,
    messages: List[Any],  # ← 这是从 UI 提取的消息，只有 5 条
    device_serial: str = "",
) -> Optional[str]:
    # ...
    # 直接使用传入的 messages 构建上下文，不查询数据库
    for msg in messages:
        role = "AGENT" if getattr(msg, 'is_self', False) else "CUSTOMER"
        content = getattr(msg, 'content', '') or "[media]"
        context_lines.append(f"{role}: {content}")
```

调用处（第 461 行）：

```python
reply = await self._generate_reply(user_name, messages[-5:], serial)  # ← 只传入 5 条 UI 消息
```

#### scanner.py 问题

在 `_handle_kefu_last_message()` 方法（第 766-768 行）中：

```python
if settings.use_ai_reply:
    tree = await wecom.adb.get_ui_tree()  # ← 只从 UI 树获取
    messages = wecom.ui_parser.extract_conversation_messages(tree) if tree else []
    msg_text = await self._generate_ai_followup_message(user_name, messages, serial, ...)
```

### FollowUp 流程的上下文来源

| 特性             | 值                        |
| ---------------- | ------------------------- |
| **数据来源**     | 📱 手机 UI 树实时提取     |
| **消息数量**     | 最近 **5 条**（可见消息） |
| **是否包含历史** | ❌ 只有当前屏幕可见的消息 |
| **上下文完整性** | ❌ 不完整                 |

### FollowUp 流程数据流

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FollowUp 流程 - 上下文不足 ❌                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  _process_unread_user_with_wait()                                           │
│         │                                                                   │
│         │  messages = await _extract_visible_messages()                     │
│         ▼                                                                   │
│  adb shell uiautomator dump  → UI 树                                        │
│         │                                                                   │
│         │  ui_parser.extract_conversation_messages(tree)                    │
│         ▼                                                                   │
│  可见消息列表（3-8 条，取决于屏幕大小）                                       │
│         │                                                                   │
│         │  messages[-5:] 只取最近 5 条                                       │
│         ▼                                                                   │
│  _generate_reply(user_name, messages[-5:], serial)                          │
│         │                                                                   │
│         ▼                                                                   │
│  ❌ AI 只能看到 5 条消息，错过重要的对话背景                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 问题对比总结

### 各流程上下文使用情况

| 流程                             | 数据来源  | 消息数量 | 上下文完整性 | 需要修改 |
| -------------------------------- | --------- | -------- | ------------ | -------- |
| **Generate 按钮（前端）**        | 📊 数据库 | 10 条    | ✅ 完整      | 否       |
| **Sync 流程（后端）**            | 📊 数据库 | 10 条    | ✅ 完整      | 否       |
| **FollowUp - response_detector** | 📱 UI 树  | 5 条     | ❌ 不足      | **是**   |
| **FollowUp - scanner**           | 📱 UI 树  | 可变     | ❌ 不足      | **是**   |

### 问题根因

FollowUp 流程在设计时可能考虑到：

1. **实时性需求**：需要处理刚刚收到的消息
2. **避免 I/O 开销**：直接从 UI 提取更快

但实际上：

1. **消息已在 Step 3 写入数据库**：在 `_generate_reply()` 调用前，`_store_messages_to_db()` 已执行完成
2. **历史消息更重要**：AI 需要完整上下文才能生成准确回复

### 修复目标

将 FollowUp 流程的上下文获取方式改为与 Sync 流程一致，从数据库读取最近 10 条消息。

---

## 影响范围

### 需要修改的流程

| 功能               | 文件                                                     | 影响程度 |
| ------------------ | -------------------------------------------------------- | -------- |
| 响应检测器 AI 回复 | `backend/servic../03-impl-and-arch/response_detector.py` | 🔴 严重  |
| 补刀扫描 AI 生成   | `backend/servic../03-impl-and-arch/scanner.py`           | 🔴 严重  |

### 无需修改的流程

| 功能          | 文件                                                    | 原因              |
| ------------- | ------------------------------------------------------- | ----------------- |
| Generate 按钮 | `wecom-desktop/src/views/SidecarView.vue`               | 已从数据库读取    |
| Sync AI 回复  | `src/wecom_automation/services/sync/customer_syncer.py` | ✅ 已从数据库读取 |

---

## 修复方案

### 推荐方案：复用 Sync 流程的数据库读取逻辑

**核心思想**：FollowUp 流程应与 Sync 流程使用相同的数据库读取方式，确保上下文一致性。

**参考实现**：`customer_syncer.py` 的 `_get_conversation_history()` 方法已正确实现，可作为参照。

### 方案对比

| 方案               | 描述                     | 优点                     | 缺点                       |
| ------------------ | ------------------------ | ------------------------ | -------------------------- |
| **方案 A（推荐）** | 从数据库读取历史消息     | 上下文完整，与 Sync 一致 | 需要确保消息先写入数据库   |
| **方案 B**         | 增加 UI 提取数量（滚动） | 不依赖数据库             | 可能干扰用户界面，实现复杂 |
| **方案 C**         | 混合方案 UI + 数据库     | 最完整的上下文           | 实现复杂度最高             |

### 为什么方案 A 可行？

经过分析（见[数据库写入时序分析](#数据库写入时序分析)）：

1. **Step 3 先于 Step 4 执行**：`_store_messages_to_db()` 在 `_generate_reply()` 前完成
2. **同步写入**：SQLite 写入是同步的，函数返回时消息已在数据库
3. **历史消息已存在**：之前同步过程中存储的消息也在数据库中

---

## 实现细节

### 修改点 1：response_detector.py

**文件**：`backend/servic../03-impl-and-arch/response_detector.py`

**修改**：在 `_generate_reply()` 中，增加从数据库读取历史消息的逻辑

```python
# 修改前
async def _generate_reply(self, user_name: str, messages: List[Any], serial: str) -> Optional[str]:
    # 直接使用 UI 提取的消息
    context_messages = messages[-5:]
    ...

# 修改后
async def _generate_reply(self, user_name: str, messages: List[Any], serial: str, channel: str = "wecom") -> Optional[str]:
    # 1. 尝试从数据库获取更完整的历史消息
    db_messages = await self._get_db_conversation_history(user_name, channel, limit=10)

    # 2. 如果数据库有足够的消息，使用数据库消息
    if len(db_messages) >= 5:
        context_messages = db_messages[-10:]  # 使用最近 10 条
    else:
        # 3. 回退到 UI 提取的消息 + 数据库消息合并
        context_messages = self._merge_messages(db_messages, messages[-5:])
    ...
```

### 修改点 2：添加数据库查询方法

```python
async def _get_db_conversation_history(
    self,
    contact_name: str,
    channel: str,
    limit: int = 10
) -> List[Dict]:
    """从数据库获取对话历史"""
    try:
        from services.database.message_service import get_message_service
        message_service = get_message_service()

        messages = await message_service.get_conversation_messages(
            contact_name=contact_name,
            channel=channel,
            limit=limit
        )

        # 转换为 AI 所需的格式
        return [
            {
                "content": msg.content,
                "is_from_kefu": msg.is_from_kefu,
                "timestamp": msg.created_at
            }
            for msg in messages
        ]
    except Exception as e:
        self._logger.warning(f"Failed to get DB conversation history: {e}")
        return []
```

### 修改点 3：scanner.py

**文件**：`backend/servic../03-impl-and-arch/scanner.py`

应用相同的修改逻辑到 `_generate_ai_followup_message()` 方法。

---

## 测试验证

### 测试场景

| 测试 ID | 场景                              | 验证点               |
| ------- | --------------------------------- | -------------------- |
| TC-01   | 长对话（20+ 条消息）的 AI 回复    | 回复应考虑完整上下文 |
| TC-02   | 新对话（仅 2-3 条消息）的 AI 回复 | 应正常工作，优雅降级 |
| TC-03   | 数据库连接失败时                  | 应回退到 UI 提取方式 |

### 对比测试

1. **修改前**：使用后端 AI Reply 生成回复，记录质量
2. **修改后**：相同场景再次生成回复，对比质量

### 验收标准

| 标准       | 描述                                      |
| ---------- | ----------------------------------------- |
| 上下文数量 | 后端 AI Reply 应使用至少 10 条历史消息    |
| 回复质量   | 应与 Generate 按钮生成的回复质量相当      |
| 错误处理   | 数据库不可用时应优雅降级到 UI 提取        |
| 性能       | 数据库查询不应显著增加响应时间（< 100ms） |

---

## 数据库写入时序分析

> **关键问题**：方案 A 的可行性取决于消息是否在 AI 回复生成前已写入数据库。

### response_detector.py 时序分析

**文件**：`backend/servic../03-impl-and-arch/response_detector.py`
**函数**：`_process_unread_user_with_wait()`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    _process_unread_user_with_wait 执行流程                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Step 1: 进入聊天界面                                                        │
│          click_user_in_list(user_name)                                      │
│          await asyncio.sleep(1.0)                                           │
│                                                                             │
│  Step 2: 从 UI 提取可见消息                                                  │
│          messages = await _extract_visible_messages(wecom, serial)          │
│          ↳ 只能获取当前屏幕可见的消息（约 3-8 条）                            │
│                                                                             │
│  Step 3: 存储消息到数据库 ← ✅ 消息已写入数据库                               │
│          stored_count = await _store_messages_to_db(...)                    │
│          ↳ 调用 ConversationRepository.add_message_if_not_exists()          │
│          ↳ 消息立即同步写入 SQLite                                           │
│                                                                             │
│  Step 4: 生成 AI 回复 ← ❌ 但这里只使用 messages[-5:]，不读数据库             │
│          reply = await _generate_reply(user_name, messages[-5:], serial)    │
│          ↳ 虽然消息已在数据库，但此处使用的是 Step 2 提取的消息                │
│                                                                             │
│  Step 5: 发送回复                                                            │
│          success, sent_text = await _send_reply_wrapper(...)                │
│                                                                             │
│  Step 6: 交互等待循环（可能多轮对话）                                         │
│          await _interactive_wait_loop(...)                                  │
│                                                                             │
│  Step 7: 返回列表                                                            │
│          await wecom.go_back()                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 关键发现

| 步骤   | 操作           | 数据库状态    | 问题                            |
| ------ | -------------- | ------------- | ------------------------------- |
| Step 2 | UI 提取消息    | -             | 只有屏幕可见消息                |
| Step 3 | **写入数据库** | ✅ 消息已存储 | -                               |
| Step 4 | 生成 AI 回复   | 消息已在库中  | ❌ **但代码没有从数据库读取！** |

### 结论

**✅ 数据库写入时序支持方案 A！**

原因：

1. **Step 3 先于 Step 4 执行**：消息存储在 AI 回复生成之前完成
2. **同步写入**：`add_message_if_not_exists()` 是同步操作，函数返回时消息已在数据库
3. **历史消息已存在**：之前同步过程中存储的消息也在数据库中

**问题不在于消息未写入数据库，而是 `_generate_reply()` 没有利用数据库中的历史消息！**

---

### scanner.py 时序分析

**文件**：`backend/servic../03-impl-and-arch/scanner.py`
**函数**：`_handle_kefu_last_message()`

```python
# 第 766-768 行
if settings.use_ai_reply:
    tree = await wecom.adb.get_ui_tree()
    messages = wecom.ui_parser.extract_conversation_messages(tree) if tree else []
    msg_text = await self._generate_ai_followup_message(user_name, messages, serial, ...)
```

这里同样存在问题：

- 直接从 UI 树提取消息
- 没有查询数据库中的历史消息
- 可能错过重要的对话上下文

---

## 最终诊断

| 诊断项         | 结果                                  |
| -------------- | ------------------------------------- |
| 数据库写入时序 | ✅ 支持（消息先写后用）               |
| 历史消息可用性 | ✅ 数据库中有完整历史                 |
| 代码实现问题   | ❌ `_generate_reply()` 没有读取数据库 |
| 方案可行性     | ✅ **方案 A 完全可行**                |

---

## 更新后的修复方案

### 修改 1：response_detector.py - \_generate_reply()

**修改点**：在 `_generate_reply()` 开始处，从数据库获取更多历史消息

```python
async def _generate_reply(
    self,
    user_name: str,
    messages: List[Any],  # 保留原参数用于回退
    device_serial: str = "",
    user_channel: Optional[str] = None,  # 新增参数
) -> Optional[str]:
    """
    生成 AI 回复

    优先从数据库获取更多历史上下文（10 条），以提高回复质量。
    如果数据库不可用，回退到使用传入的 UI 提取消息。
    """

    # 1. 尝试从数据库获取更完整的历史消息
    context_messages = messages  # 默认使用传入的 UI 消息

    try:
        from wecom_automation.database.repository import ConversationRepository
        repo = ConversationRepository(self._repository._db_path)

        # 获取 customer_id
        customer_id = self._repository.find_or_create_customer(user_name, user_channel)

        if customer_id:
            # 查询最近 10 条消息
            db_messages = repo.get_recent_messages(customer_id, limit=10)

            if len(db_messages) >= 5:
                self._logger.debug(f"[{device_serial}] Using {len(db_messages)} messages from DB for AI context")
                # 转换为 _generate_reply 所需的格式
                context_messages = [
                    SimpleNamespace(
                        is_self=msg.is_from_kefu,
                        content=msg.content,
                        timestamp=msg.timestamp_raw,
                    )
                    for msg in db_messages
                ]
            else:
                self._logger.debug(f"[{device_serial}] DB has only {len(db_messages)} messages, using UI messages")
    except Exception as e:
        self._logger.debug(f"[{device_serial}] Failed to get DB history: {e}, using UI messages")

    # 2. 继续使用 context_messages 构建 AI 上下文
    # ... 其余逻辑保持不变 ...
```

### 修改 2：调用处传递 user_channel

在 `_process_unread_user_with_wait()` 第 461 行：

```python
# 修改前
reply = await self._generate_reply(user_name, messages[-5:], serial)

# 修改后
reply = await self._generate_reply(user_name, messages[-5:], serial, user_channel)
```

### 修改 3：添加 get_recent_messages 方法

`ConversationRepository` 已有 `get_messages_for_customer()` 方法，但它返回的是按时间**正序**排列的所有消息。
我们需要一个**倒序**获取最近 N 条消息的方法：

**文件**：`src/wecom_automation/database/repository.py`

```python
def get_recent_messages_for_customer(
    self,
    customer_id: int,
    limit: int = 10,
) -> List[MessageRecord]:
    """
    获取客户最近的 N 条消息（用于 AI 上下文）。

    Args:
        customer_id: Customer ID.
        limit: Maximum number of messages to return.

    Returns:
        List of MessageRecord ordered by time (oldest first for chat context).
    """
    with self._connection() as conn:
        cursor = conn.cursor()
        # 先倒序获取最近 N 条，再正序返回（保持对话顺序）
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

**注意**：这个方法返回的消息是按时间正序排列的（最早的在前），这样在构建 AI 上下文时可以直接使用，保持对话的自然顺序。

---

## 文件变更清单

### 需修改的文件（FollowUp 流程）

| 文件                                                                   | 操作     | 说明                                                  |
| ---------------------------------------------------------------------- | -------- | ----------------------------------------------------- |
| `src/wecom_automation/database/repository.py`                          | 添加方法 | 添加 `get_recent_messages_for_customer()` 方法        |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 修改     | 修改 `_generate_reply()` 使用数据库历史               |
| `wecom-desktop/backend/servic../03-impl-and-arch/scanner.py`           | 修改     | 修改 `_generate_ai_followup_message()` 使用数据库历史 |

### 无需修改的文件

| 文件                                                    | 流程 | 原因                                                 |
| ------------------------------------------------------- | ---- | ---------------------------------------------------- |
| `src/wecom_automation/services/sync/customer_syncer.py` | Sync | ✅ 已正确使用数据库（`_get_conversation_history()`） |
| `wecom-desktop/src/views/SidecarView.vue`               | 前端 | 已正确使用数据库                                     |
| `wecom-desktop/src/services/aiService.ts`               | 前端 | AI 服务接口无需变更                                  |

---

## 实施优先级

| 优先级 | 任务                                                   | 工作量 |
| ------ | ------------------------------------------------------ | ------ |
| P0     | 添加 `get_recent_messages_for_customer()` 方法         | 小     |
| P1     | 修改 `response_detector.py` 的 `_generate_reply()`     | 中     |
| P2     | 修改 `scanner.py` 的 `_generate_ai_followup_message()` | 中     |
| P3     | 测试验证                                               | 中     |

### 已正确实现的流程（作为参考）

| 流程          | 文件                 | 关键方法                      |
| ------------- | -------------------- | ----------------------------- |
| Sync AI 回复  | `customer_syncer.py` | `_get_conversation_history()` |
| Generate 按钮 | `SidecarView.vue`    | `fetchConversationHistory()`  |

---

## 相关文档

- [AI 提示词和上下文拼接逻辑文档](../ai_prompt_context_logic.md)
- [补刀模式检测与提示词变化分析](../followup_mode_prompt_analysis.md)
