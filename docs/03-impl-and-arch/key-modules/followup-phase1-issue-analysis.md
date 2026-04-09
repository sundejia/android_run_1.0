# Follow-up 阶段一红点检测 - 已修复

## 最新实现 (2026-01-01)

### 代码位置

- `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

### 新流程

```
1. 打开企业微信
   ↓
2. 切换到私聊标签
   ↓
3. 滚动到顶部
   ↓
4. ✅ 只检测第一页红点用户（不滚动）
   ↓
5. ✅ 对每个有红点的用户：
   - 进入聊天
   - 提取消息（不滚动）
   - 写入数据库
   - 生成AI回复
   - 发送回复
   - 等待新消息（40s超时）
   - 如果有新消息，继续回复
   ↓
6. 返回后重新检测红点
   ↓
7. ✅ 如果有新红点，优先处理（加入队首）
   ↓
8. ✅ 如果没有新红点，继续处理下一个用户
   ↓
9. 循环直到没有红点
```

### 核心方法

#### 1. `detect_and_reply` - 主入口

```python
async def detect_and_reply(
    self,
    device_serial: Optional[str] = None,
    interactive_wait_timeout: int = 40,  # 等待新消息的超时时间
) -> Dict[str, Any]:
```

#### 2. `_scan_device_for_responses` - 设备扫描

- 使用 `deque` 队列管理红点用户
- 处理完一个用户后，重新检测红点
- 新红点优先处理（加入队首）

```python
# 使用队列动态处理红点
user_queue: deque = deque(initial_unread)
queued_names: Set[str] = {u.name for u in initial_unread}
processed_names: Set[str] = set()

while user_queue and not self._cancel_requested:
    user = user_queue.popleft()

    # 处理用户...
    await self._process_unread_user_with_wait(...)

    # 重新检测红点
    new_unread = await self._detect_first_page_unread(wecom, serial)

    # 新红点加入队首
    for u in new_users:
        user_queue.appendleft(u)
```

#### 3. `_process_unread_user_with_wait` - 处理单个用户

```python
async def _process_unread_user_with_wait(
    self, wecom, serial, unread_user, pending_map,
    interactive_wait_timeout=40
):
    # 1. 进入聊天
    # 2. 提取消息（不滚动）
    # 3. 写入数据库
    # 4. 生成AI回复
    # 5. 发送回复
    # 6. 交互等待循环（40s）
    # 7. 返回列表
```

#### 4. `_interactive_wait_loop` - 交互等待

```python
async def _interactive_wait_loop(
    self, wecom, serial, user_name, user_channel,
    initial_messages, pending_map, result,
    timeout=40
):
    # 等待新消息
    # 如果有新客户消息 → 回复
    # 超时后退出
```

### 特性

| 特性                      | 状态   |
| ------------------------- | ------ |
| ✅ 只检测第一页红点       | 已实现 |
| ✅ 动态红点优先处理       | 已实现 |
| ✅ 消息写入数据库         | 已实现 |
| ✅ AI回复                 | 已实现 |
| ✅ 交互等待（40s）        | 已实现 |
| ✅ 发送消息存储           | 已实现 |
| ✅ pending follow-up 标记 | 已实现 |

### 与阶段二的对比

| 阶段       | 检测范围            | 处理逻辑                                   | 交互等待 |
| ---------- | ------------------- | ------------------------------------------ | -------- |
| **阶段一** | ✅ 只检测第一页红点 | 进入聊天 → 提取消息 → 存储 → AI回复 → 等待 | ✅ 40s   |
| **阶段二** | ✅ 只检测第一页红点 | 进入聊天 → 发送跟进消息                    | ❌ 无    |

### 日志示例

```
============================================================
PHASE 1: RESPONSE DETECTION (Red Dot Prioritized)
============================================================
[serial] Step 1: Launching WeCom...
[serial] Step 2: Switching to Private Chats...
[serial] Step 3: Scrolling to top...
[serial] Step 4: Detecting red dot users (first page only)...
[serial] 🔴 Found 2 red dot users, adding to queue
[serial] [1] 🔴 Processing: 张三 (queue: 1 remaining)
[serial]    Step 1: Entering chat...
[serial]    Step 2: Extracting visible messages...
[serial]    Extracted 8 messages
[serial]    Step 3: Storing messages to database...
[serial]    Stored 5 new messages
[serial]    Step 4: Last customer message: 你好，请问...
[serial]    Sending reply: 您好，感谢您的咨询...
[serial]    ✅ Reply sent!
[serial]    ⏳ Waiting for new messages (timeout=40s)...
[serial]    📨 Round 1: Found 1 new customer message(s)
[serial]    ✅ Reply sent: 好的，我来为您解答...
[serial]    ⏰ Timeout (40s), exiting wait loop
[serial]    Returning to list...
[serial] Checking for new red dots...
[serial] 🆕 Found 1 new/reprocess red dots, adding to queue front
[serial] [2] 🔴 Processing: 李四 (queue: 1 remaining)
...
[serial] ✅ Queue empty, all red dot users processed
============================================================
PHASE 1 COMPLETE
============================================================
```
