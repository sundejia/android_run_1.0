# 调查：Blacklist 界面 Blocked 用户仍被点击进入

**日期**: 2026-02-03  
**状态**: 调查中  
**关联 Bug**: `2026-02-03-blacklist-cache-not-synced.md`

---

## 问题描述

用户报告：在 Blacklist 界面显示为 Blocked 的用户，Follow-up 系统仍然会点击进入该聊天。

---

## 调查结论

**这很可能是同一个问题**，但需要满足以下条件才能生效：

### 1. ✅ 代码已修复

`BlacklistChecker.is_blacklisted()` 已修改为默认直接查询数据库：

```python
# src/wecom_automation/services/blacklist_service.py
@classmethod
def is_blacklisted(cls, device_serial, customer_name, customer_channel, use_cache=False):
    if use_cache:
        # 使用缓存（可能过期）
        ...
    else:
        # 默认：直接查询数据库
        cursor.execute("""
            SELECT 1 FROM blacklist
            WHERE device_serial = ? AND customer_name = ? AND is_blacklisted = 1
            LIMIT 1
        """, ...)
```

### 2. ⚠️ 需要重启 Follow-up 进程

**关键点**：Follow-up 系统运行在独立的子进程中 (`realtime_reply_process.py`)，代码修改后必须重启进程才能生效。

**如何重启 Follow-up 进程：**

1. 在 Sidecar 页面点击 **Stop** 按钮停止 Follow-up
2. 等待几秒
3. 点击 **Start** 按钮重新启动 Follow-up

或者通过 API：

```bash
# 停止
curl -X POST http://localhost:87../03-impl-and-arch/key-modules/realtime/device/{serial}/stop

# 启动
curl -X POST http://localhost:87../03-impl-and-arch/key-modules/realtime/device/{serial}/start
```

---

## 验证步骤

1. **确认进程已重启**
   - 在 Sidecar 页面查看日志，应该看到 "Starting follow-up..." 消息

2. **确认黑名单检查生效**
   - 查看日志中是否有 `⛔ Skipping blacklisted user: XXX` 消息
   - 如果没有这条日志，说明黑名单检查可能有问题

3. **检查数据库实际状态**
   ```sql
   SELECT * FROM blacklist
   WHERE customer_name = '用户名' AND is_blacklisted = 1;
   ```

---

## 可能的其他原因

如果重启后问题仍然存在，可能是以下原因：

### A. 数据库中 `is_blacklisted` 字段值不对

Blacklist 界面显示 "Blocked" 可能基于不同的查询逻辑。

检查数据库：

```sql
SELECT id, device_serial, customer_name, is_blacklisted, updated_at
FROM blacklist
WHERE customer_name LIKE '%用户名%';
```

如果 `is_blacklisted = 0`，说明用户实际上不是黑名单。

### B. `customer_channel` 不匹配

黑名单检查包含 `customer_channel` 字段。如果：

- 黑名单记录：`(customer_name='张三', customer_channel='@WeChat')`
- 检查时传入：`(customer_name='张三', customer_channel=None)`

则不会匹配！

检查日志中传入的参数是否正确。

### C. 异常被静默吞掉

检查是否有日志显示：

```
Failed to check blacklist from DB, falling back to cache: ...
```

如果有，说明数据库查询失败了。

---

## 代码调用链分析

```
response_detector.py :: _process_single_user()
│
├── 第 897-902 行: 确保用户在黑名单表中
│   BlacklistService().ensure_user_in_blacklist_table(...)
│
├── 第 905-908 行: ⭐ 黑名单检查
│   if BlacklistChecker.is_blacklisted(serial, user_name, user_channel):
│       return result  # 跳过，不点击
│
├── 第 910-919 行: 捕获头像
│
└── 第 942 行: 点击用户进入聊天
    clicked = await wecom.click_user_in_list(user_name, user_channel)
```

黑名单检查逻辑是正确的：如果 `is_blacklisted()` 返回 `True`，函数会在第 908 行直接返回，不会执行到第 942 行的点击操作。

---

## 后续行动

1. [ ] 停止并重启 Follow-up 进程
2. [ ] 观察日志中是否有 `⛔ Skipping blacklisted user` 消息
3. [ ] 如果问题仍存在，检查数据库中 `is_blacklisted` 字段实际值
4. [ ] 如果仍有问题，添加更详细的日志以追踪问题

---

## 紧急临时方案

如果需要立即阻止某用户，可以使用 SQL 强制确认黑名单状态：

```sql
UPDATE blacklist
SET is_blacklisted = 1, updated_at = CURRENT_TIMESTAMP
WHERE customer_name = '用户名' AND device_serial = '设备序列号';
```

然后重启 Follow-up 进程。
