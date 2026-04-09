# Sync 流程用户删除检测功能

## 概述

在 Sync 流程中增加对用户删除/拉黑消息的检测，当检测到用户已删除/拉黑时，自动将该用户加入黑名单，后续不再处理。

## 问题背景

### 当前状态

| 功能点                     | Sync 流程   | FollowUp 流程 |
| -------------------------- | ----------- | ------------- |
| 进入对话前检查黑名单       | ✅ 有       | ✅ 有         |
| 解析聊天记录时检测用户删除 | ❌ **没有** | ✅ 有         |
| 自动加入黑名单             | ❌ 没有     | ✅ 有         |

### 问题描述

当 Sync 流程进入一个已被用户删除的对话时：

- 能正确解析出系统消息（`message_type="system"`）
- **但不会检测该系统消息是否表示用户已删除**
- **也不会自动将该用户加入黑名单**

### 影响

- 浪费资源尝试处理错误的对话
- 后续仍会尝试给该用户发送消息（会失败）
- 无法及时清理无效用户

## 现有实现参考

### 1. 用户删除检测方法

**文件**: `src/wecom_automation/services/ui_parser.py`

```python
# 第 1427-1439 行
def is_user_deleted_message(self, text: str) -> bool:
    """Check if text indicates the user has deleted/blocked us."""
    deletion_patterns = (
        "has enabled verification for contacts",
        "Send a verification request",
        "You're not his/her contact",
        "开启了联系人验证",
        "发起验证请求",
        "你还不是他的企业联系人",
        "你还不是她的企业联系人",
    )
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in deletion_patterns)
```

### 2. FollowUp 流程的实现

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

```python
# 第 488-507 行
for msg in messages:
    content = getattr(msg, 'content', '') or ''
    if getattr(msg, 'message_type', '') == 'system' and wecom.ui_parser.is_user_deleted_message(content):
        self._logger.info(f"[{serial}] 🚫 Detected user deletion message: {content}")
        from wecom_automation.services.blacklist_service import BlacklistService
        service = BlacklistService()
        service.add_to_blacklist(
            device_serial=serial,
            customer_name=user_name,
            customer_channel=user_channel,
            reason="User deleted/blocked",
            deleted_by_user=True
        )
        self._logger.info(f"[{serial}] ✅ Automatically added {user_name} to blacklist")

        # Store this system message and return early
        await self._store_messages_to_db(user_name, user_channel, [msg], serial)
        await wecom.go_back()
        await asyncio.sleep(0.5)
        return result
```

## 实现方案

### 修改位置

**文件**: `src/wecom_automation/services/sync/customer_syncer.py`

### 修改方法

在 `sync` 方法的消息处理循环中（第 167-185 行），增加用户删除检测逻辑。

### 具体实现

```python
# 在 sync 方法中，第 166-186 行之间修改

# 5. 处理每条消息
for msg in messages:
    try:
        # ========== 新增：检测用户删除消息 ==========
        msg_type = getattr(msg, 'message_type', 'text')
        msg_content = getattr(msg, 'content', '') or ''

        if msg_type == 'system' and self._wecom.ui_parser.is_user_deleted_message(msg_content):
            self._logger.warning(f"🚫 Detected user deletion message: {msg_content}")

            # 导入黑名单服务并加入黑名单
            from wecom_automation.services.blacklist_service import BlacklistService
            service = BlacklistService()
            service.add_to_blacklist(
                device_serial=device_serial,
                customer_name=user_name,
                customer_channel=user_channel,
                reason="User deleted/blocked",
                deleted_by_user=True
            )
            self._logger.info(f"✅ Automatically added {user_name} to blacklist")

            # 仍然存储这条系统消息（用于记录）
            process_result = await self._message_processor.process(msg, context)
            if process_result.added:
                result.messages_added += 1

            # 标记为用户被删除，退出对话
            result.user_deleted = True
            await self._exit_conversation()
            return result
        # ========== 新增结束 ==========

        process_result = await self._message_processor.process(msg, context)
        # ... 原有逻辑
```

### 需要修改的类

1. **CustomerSyncResult** - 添加 `user_deleted` 字段

**文件**: `src/wecom_automation/core/interfaces.py`

```python
@dataclass
class CustomerSyncResult:
    success: bool = True
    messages_count: int = 0
    messages_added: int = 0
    messages_skipped: int = 0
    images_saved: int = 0
    videos_saved: int = 0
    voice_count: int = 0
    error: Optional[str] = None
    skipped: bool = False
    user_deleted: bool = False  # 新增字段
```

## 任务清单

### Task 1: 修改 CustomerSyncResult 数据类

- **文件**: `src/wecom_automation/core/interfaces.py`
- **内容**: 添加 `user_deleted: bool = False` 字段
- **复杂度**: 低

### Task 2: 修改 CustomerSyncer.sync 方法

- **文件**: `src/wecom_automation/services/sync/customer_syncer.py`
- **内容**: 在消息处理循环中增加用户删除检测逻辑
- **复杂度**: 中
- **依赖**: Task 1

### Task 3: 更新 sync_service.py 处理 user_deleted 标记

- **文件**: `src/wecom_automation/services/sync_service.py`
- **内容**: 在 `run_initial_sync` 中处理返回的 `user_deleted` 标记，记录日志
- **复杂度**: 低
- **依赖**: Task 1, Task 2

## 测试计划

1. **单元测试**: 测试 `is_user_deleted_message` 方法对各种模式的匹配
2. **集成测试**: 模拟进入已删除用户的对话，验证：
   - 正确识别系统消息
   - 自动加入黑名单
   - 正确退出对话
   - 后续 Sync 不再处理该用户

## 日志输出示例

```
Processing customer 5/20: 张三
🚫 Detected user deletion message: 对方开启了联系人验证，你还不是他的企业联系人
✅ Automatically added 张三 to blacklist
⛔ User 张三 deleted/blocked, skipping
```

## 注意事项

1. **黑名单服务导入**: 使用延迟导入避免循环依赖
2. **消息仍需存储**: 系统消息应被存储用于历史记录
3. **早期退出**: 检测到删除后应立即退出对话，不继续处理其他消息
4. **状态传播**: `user_deleted` 标记需要正确传播到上层调用

---

**创建时间**: 2026-01-21
**状态**: 待实现
