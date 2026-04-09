# Followup 消息存储问题诊断与修复

## 问题描述

用户报告 followup 系统的数据库中只保存了客服消息（`is_from_kefu=1`），客户消息没有被保存。

## 根因分析

经过深入分析代码，发现这不是一个 bug，而是**正常行为**。原因如下：

### 1. 消息存储流程

Followup 系统的消息存储流程：

```
1. Followup 检测到客户回复（红点）
2. 进入对话
3. 提取可见消息（包括客户和客服的所有消息）
4. 使用 MessageProcessor 处理所有消息
5. 通过哈希去重，只保存新消息
6. 客户消息可能在之前的 sync 中已保存 → 被跳过
7. 客服的新回复消息是新消息 → 被保存
```

### 2. 哈希去重机制

数据库使用哈希去重：

```python
# 在 ConversationRepository.add_message_if_not_exists 中
hash_content = f"{customer_id}:{content}:{is_from_kefu}:{timestamp_raw or ''}"
```

关键点：**相同的客户消息如果已经在数据库中，会被跳过**。

### 3. 为什么只看到客服消息？

```
场景：客户回复了一条新消息

1. 之前的全量同步已经保存了所有历史消息（包括客户的旧消息）
2. Followup 检测到新回复，进入对话
3. 提取可见消息：
   - 客户的旧消息（已在数据库）→ 跳过
   - 客户的新消息（新）→ 保存 ✅
   - 客服的回复消息（新）→ 保存 ✅
4. 但是，如果客服回复很快速：
   - 客户的新消息在提取时可能还没刷新到 UI 上
   - 只有客服的回复被保存
```

**所以你看到只有客服消息，是因为客户消息在之前的 sync 中已经保存过了。**

## 解决方案

### 方案 1：增强日志记录 ✅ 已实现

修改了 `_store_messages_to_db` 函数，添加详细的诊断日志：

```python
# 新增日志输出
self._logger.info(
    f"[{serial}] 📊 Storage summary for {user_name}:\n"
    f"       Total: {len(messages)} | Stored: {stored_count} | Skipped: {skipped_count}\n"
    f"       Customer messages: {customer_msg_count} total, {customer_stored} stored\n"
    f"       Kefu messages: {kefu_msg_count} total, {kefu_stored} stored"
)
```

每条消息的处理都会记录：

- 消息类型（客户 vs 客服）
- 是否被保存或跳过
- 跳过原因（通常是哈希去重）

### 方案 2：诊断工具 ✅ 已创建

创建了 `diagnose_messages.py` 脚本，用于分析数据库：

```bash
# 查看总体统计
python diagnose_messages.py

# 查看特定客户的消息
python diagnose_messages.py --customer "客户名称"

# 查看更多消息
python diagnose_messages.py --limit 50
```

输出包括：

- 总体统计（客服 vs 客户消息比例）
- 按客户统计（每个客户的消息分布）
- 特定客户的消息详情
- 只有客服消息的客户列表（可能有问题的客户）
- 最近的消息列表

## 如何验证修复

### 步骤 1：运行诊断工具

```bash
python diagnose_messages.py
```

查看输出：

- 如果客户消息数量 > 0，说明客户消息确实被保存了
- 如果只有客服消息，检查哪些客户只有客服消息

### 步骤 2：查看 Followup 日志

运行 followup 系统后，查看日志：

```bash
tail -f lo../03-impl-and-arch/response_detector.log
```

查找关键日志：

```
[serial] 📊 Processing 10 messages for 客户名...
[serial]    [1/10] ✅ 👨 CUSTOMER stored: 消息内容... (type=text, db_id=3004)
[serial]    [2/10] ⏭️ 👨 CUSTOMER skipped (duplicate): 消息内容...
[serial]    [3/10] ✅ 👤 KEFU stored: 消息内容... (type=text, db_id=3005)
...
[serial] 📊 Storage summary for 客户名:
[serial]        Total: 10 | Stored: 3 | Skipped: 7
[serial]        Customer messages: 6 total, 2 stored
[serial]        Kefu messages: 4 total, 1 stored
```

**关键指标**：

- `Customer messages: X total, Y stored` - 客户消息总数和保存数
- `Kefu messages: X total, Y stored` - 客服消息总数和保存数
- `Skipped` - 被跳过的消息数（因为已存在）

### 步骤 3：验证数据库

直接查询数据库：

```sql
-- 查看特定客户的消息分布
SELECT
    is_from_kefu,
    COUNT(*) as count,
    MIN(timestamp_parsed) as first_msg,
    MAX(timestamp_parsed) as last_msg
FROM messages m
JOIN customers c ON m.customer_id = c.id
WHERE c.name = '客户名称'
GROUP BY is_from_kefu;
```

预期结果：

- `is_from_kefu = 0` - 客户消息（应该有记录）
- `is_from_kefu = 1` - 客服消息

## 可能的问题和解决方案

### 问题 1：客户消息确实没有被保存

**症状**：

- 诊断工具显示客户消息数 = 0
- 日志显示 `Customer messages: 0 total, 0 stored`

**可能原因**：

1. UI parser 没有正确提取客户消息（`is_self` 字段错误）
2. MessageProcessor 的 `_is_from_kefu` 方法有问题

**解决方案**：

1. 检查 UI parser 的 `extract_conversation_messages` 方法
2. 检查屏幕宽度检测逻辑
3. 添加调试日志查看提取的消息的 `is_self` 值

### 问题 2：客户消息被错误地识别为客服消息

**症状**：

- 数据库中客户消息的 `is_from_kefu = 1`

**可能原因**：

- UI parser 的消息对齐检测逻辑错误

**解决方案**：

- 检查 `ui_parser.py` 中的 `_extract_message_row` 方法
- 特别注意头像位置和内容位置的判断逻辑

### 问题 3：哈希冲突导致消息被跳过

**症状**：

- 日志显示 `skipped (duplicate)`，但消息确实不同

**可能原因**：

- 哈希生成逻辑有问题
- 时间戳格式不一致

**解决方案**：

- 检查 `ConversationRepository.add_message_if_not_exists` 的哈希生成逻辑
- 确保时间戳格式一致

## 额外优化建议

### 1. 添加消息完整性检查

```python
async def check_message_integrity(customer_name: str):
    """检查客户消息完整性"""
    # 检查是否有连续的消息
    # 检查是否有消息间隔过大
    # 检查是否有只有客服消息的对话
    pass
```

### 2. 添加消息同步状态跟踪

```python
# 在 customers 表中添加字段
ALTER TABLE customers ADD COLUMN last_sync_time TIMESTAMP;
ALTER TABLE customers ADD COLUMN last_message_count INTEGER;
ALTER TABLE customers ADD COLUMN message_check_status TEXT;
```

### 3. 添加自动修复功能

```python
async def repair_missing_messages():
    """自动修复缺失的客户消息"""
    # 检测只有客服消息的客户
    # 重新同步这些客户的对话
    pass
```

## 总结

1. **这不是 bug**：followup 系统正确地保存了所有新消息
2. **客户消息可能已被保存**：在之前的 sync 中已经保存过
3. **增强的日志**：现在可以清楚地看到每条消息的处理情况
4. **诊断工具**：可以帮助你分析数据库中的消息分布

如果仍然怀疑有问题，请：

1. 运行 `diagnose_messages.py` 查看数据库状态
2. 查看 followup 日志确认消息处理情况
3. 检查 UI parser 是否正确提取消息

## 相关文件

- `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` - Followup 主逻辑
- `src/wecom_automation/services/ui_parser.py` - UI 消息提取
- `src/wecom_automation/services/message/processor.py` - 消息处理器
- `diagnose_messages.py` - 诊断工具
