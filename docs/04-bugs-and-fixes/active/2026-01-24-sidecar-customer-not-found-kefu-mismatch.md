# Sidecar 无法显示聊天记录：Kefu ID 不一致问题

**日期**: 2026-01-24
**状态**: 已分析 / 部分修复

## 问题现象

Sidecar 界面无法显示当前用户的聊天记录，显示 "No messages yet"。
后端日志显示：

```
Searching customer: kefu_id=21, contact_name=1854701823-..., channel=@WeChat
Exact match failed
No customer found for: name=1854701823-..., channel=@WeChat
```

但同时 Bottom Logs 显示 FollowUp 系统已经成功提取了消息：

```
[FOLLOWUP] Extracted 4 messages from conversation
```

## 根因分析

经过数据库排查，发现存在 **Kefu ID 不一致** 的问题：

1.  **后端 Sidecar 服务**：根据设备 Serial (`AN2FVB17...`) 查找最近更新的关联客服，找到了 `kefu_id=21` (`沈子涵`)。因此，它在查询数据库时，限定条件为 `WHERE kefu_id = 21`。

2.  **数据库记录**：实际的客户记录（如 `1854701823-归辞`）虽然存在，但关联的是旧的 `kefu_id=19` (`Kefu-AN2FVB17`)。
    - `Kefu-AN2FVB17` (ID 19) 可能是系统早期自动生成的默认客服名。
    - `沈子涵` (ID 21) 是系统后来正确识别到的真实客服名。

3.  **结果**：由于 Sidecar 搜索 `kefu_id=21` 下名为 `1854701823-归辞` 的客户，而该客户实际挂在 `kefu_id=19` 名下，导致搜索失败，聊天记录无法加载。

## 解决方案

### 临时修复（已执行）

针对当前受影响的客户（ID 146），手动将其迁移到正确的 Kefu ID 下：

```sql
UPDATE customers SET kefu_id = 21 WHERE id = 146;
```

### 长期建议

建议清理数据库中的冗余 Kefu 记录，将旧账号的数据完全合并到新账号下。

**SQL 迁移脚本示例**（需谨慎运行，处理 UNIQUE 冲突）：

```sql
-- 1. 将旧客服的客户迁移到新客服（忽略冲突）
UPDATE OR IGNORE customers SET kefu_id = 21 WHERE kefu_id = 19;

-- 2. 处理剩余冲突（如果有）：如果是重复的客户，可能需要通过代码逻辑合并消息，目前简单的 SQL 难以完美处理所有情况。
-- 上述语句会跳过冲突的行，意味着冲突的客户仍留在 ID 19 下。

-- 3. 清理设备关联
DELETE FROM kefu_devices WHERE kefu_id = 19;
UPDATE OR IGNORE kefu_devices SET kefu_id = 21 WHERE kefu_id = 19;

-- 4. 删除旧客服
-- DELETE FROM kefus WHERE id = 19; -- 只有当确认 19 下没有重要遗留数据时才执行
```

## 验证

请刷新 Sidecar 界面，聊天记录应该能正常显示了。
