# 补刀系统黑名单过滤功能

> 文档创建：2026-02-04
> 状态：已实现

## 背景

在补刀（FollowUp）系统中，不应该自动处理黑名单中的用户。本文档描述了如何在补刀流程中跳过黑名单用户。

## 功能概述

### 核心需求

1. **补刀时跳过黑名单用户**：在补刀扫描和实时回复检测过程中，跳过黑名单中的用户
2. **新用户自动记录**：遇到新用户时，自动记录到黑名单表（默认为白名单状态）
3. **删除好友自动加入黑名单**：如果检测到用户删除了我们，自动将其加入黑名单

## 当前实现

### 1. 黑名单服务 (`BlacklistService`)

**文件**: `wecom-desktop/backend/services/blacklist_service.py`

提供黑名单的核心功能：

```python
class BlacklistService:
    # 内存缓存，避免频繁查库
    _cache: dict[str, Set[Tuple[str, Optional[str]]]] = {}
    _cache_loaded: bool = False

    @classmethod
    def is_blacklisted(cls, device_serial, customer_name, customer_channel) -> bool:
        """检查用户是否在黑名单中"""
        pass

    def add_to_blacklist(self, device_serial, customer_name, customer_channel, reason):
        """添加用户到黑名单"""
        pass

    def ensure_user_in_blacklist_table(self, device_serial, customer_name, customer_channel):
        """确保用户在黑名单表中（默认为白名单）"""
        pass
```

### 2. 黑名单检查器 (`BlacklistChecker`)

**文件**: `wecom_automation/services/blacklist_service.py`

封装黑名单检查逻辑：

```python
class BlacklistChecker:
    @classmethod
    def is_blacklisted(cls, device_serial, customer_name, customer_channel) -> bool:
        """检查用户是否在黑名单中"""
        pass
```

### 3. 补刀流程集成 - 实时回复检测

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

在 `_process_unread_user_with_wait()` 方法中的黑名单检查：

```python
async def _process_unread_user_with_wait(self, wecom, serial, user, ...):
    user_name = unread_user.name
    user_channel = getattr(unread_user, "channel", None)

    # 1. 确保用户记录在黑名单表中（默认为白名单）
    try:
        BlacklistService().ensure_user_in_blacklist_table(serial, user_name, user_channel)
    except Exception as e:
        self._logger.warning(f"[{serial}] Failed to record user in blacklist table: {e}")

    # 2. 黑名单检查 - 如果用户在黑名单中则跳过
    if BlacklistChecker.is_blacklisted(serial, user_name, user_channel):
        self._logger.info(f"[{serial}] ⛔ Skipping blacklisted user: {user_name}")
        result["skipped"] = True
        return result

    # 3. 正常处理用户...
```

### 4. 删除好友自动加入黑名单

当检测到用户删除消息时，自动将其加入黑名单：

```python
# 检查消息是否表明用户删除了我们
for msg in messages:
    content = getattr(msg, "content", "") or ""
    if getattr(msg, "message_type", "") == "system" and wecom.ui_parser.is_user_deleted_message(content):
        self._logger.info(f"[{serial}] 🚫 Detected user deletion message: {content}")

        # 自动添加到黑名单
        service = BlacklistService()
        service.add_to_blacklist(
            device_serial=serial,
            customer_name=user_name,
            customer_channel=user_channel,
            reason="User deleted/blocked",
            deleted_by_user=True,
        )
        self._logger.info(f"[{serial}] ✅ Automatically added {user_name} to blacklist")
```

### 5. 补刀队列管理器集成

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/queue_manager.py`

在 `process_conversations()` 方法中的黑名单检查：

```python
def process_conversations(self, conversations: list[ConversationInfo]) -> dict[str, Any]:
    """处理对话列表，更新补刀队列"""
    for idx, conv in enumerate(conversations, 1):
        # ... 检查空闲阈值等逻辑 ...

        # 黑名单用户不进入补刀队列
        try:
            from wecom_automation.services.blacklist_service import BlacklistChecker

            if BlacklistChecker.is_blacklisted(
                self.device_serial,
                conv.customer_name,
                conv.customer_channel,
                use_cache=False,
            ):
                self._log("      ⛔ 黑名单用户，跳过入队")
                skipped_blacklisted += 1
                continue
        except Exception as e:
            # 黑名单检查失败时不阻断主流程，但记录日志便于排查
            self._log(f"      ⚠️ 黑名单检查失败，继续入队判断: {e}", "WARN")

        # 加入队列
        repo.add_or_update(...)
```

**关键改进**:

- 在用户加入补刀队列前进行黑名单检查
- 使用 `use_cache=False` 确保实时检查黑名单状态
- 检查失败时不阻断主流程，只记录警告日志
- 统计跳过的黑名单用户数量并在日志中显示

**ConversationInfo 数据模型扩展**:

```python
@dataclass
class ConversationInfo:
    """对话信息（用于判断是否需要补刀）"""
    customer_name: str
    customer_channel: str | None = None  # 新增：用于黑名单检查
    customer_id: str | None = None
    last_message_id: str = ""
    last_message_time: datetime | None = None
    last_message_sender: str = ""  # "kefu" 或 "customer"
```

## 数据库表结构

**表名**: `blacklist`

```sql
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,           -- 设备序列号
    customer_name TEXT NOT NULL,           -- 用户名
    customer_channel TEXT,                 -- 渠道 (如 @WeChat)
    is_blacklisted INTEGER DEFAULT 1,      -- 是否在黑名单中 (1=黑名单, 0=白名单)
    reason TEXT,                           -- 加入原因
    deleted_by_user INTEGER DEFAULT 0,     -- 是否被用户删除
    avatar_url TEXT,                       -- 头像 URL
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 唯一约束：同一设备下的用户名+渠道唯一
    UNIQUE(device_serial, customer_name, customer_channel)
);

-- 索引：加速查询
CREATE INDEX IF NOT EXISTS idx_blacklist_device ON blacklist(device_serial);
CREATE INDEX IF NOT EXISTS idx_blacklist_name ON blacklist(customer_name);
CREATE INDEX IF NOT EXISTS idx_blacklist_status ON blacklist(is_blacklisted);
```

## 处理流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        补刀流程 (Response Detector)                       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  检测到红点用户列表      │
                        └────────────┬───────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │    遍历每个用户                  │
                    └────────────────┬───────────────┘
                                     │
            ┌────────────────────────┼────────────────────────┐
            │                        │                        │
            ▼                        ▼                        ▼
    ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
    │ 用户 A        │      │ 用户 B        │      │ 用户 C        │
    └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
            │                      │                      │
            ▼                      ▼                      ▼
    ┌───────────────────────────────────────────────────────────┐
    │  Step 1: ensure_user_in_blacklist_table()                 │
    │  确保用户记录在表中（新用户默认 is_blacklisted=0）          │
    └────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
    ┌───────────────────────────────────────────────────────────┐
    │  Step 2: BlacklistChecker.is_blacklisted()                │
    │  检查用户是否在黑名单中 (is_blacklisted=1)                  │
    └────────────────────────────┬──────────────────────────────┘
                                 │
            ┌────────────────────┴────────────────────┐
            │ is_blacklisted=True                     │ is_blacklisted=False
            ▼                                         ▼
    ┌───────────────┐                        ┌───────────────┐
    │ ⛔ 跳过该用户  │                        │ ✅ 正常处理    │
    │ result.skipped│                        │ 提取消息      │
    │    = True     │                        │ 生成回复      │
    └───────────────┘                        │ 发送回复      │
                                             └───────────────┘
```

### 补刀队列管理流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        补刀队列管理 (Queue Manager)                       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  获取对话列表           │
                        │  (来自数据库查询)       │
                        └────────────┬───────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │    遍历每个对话                  │
                    └────────────────┬───────────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │ 检查最后消息发送方       │
                        └────────────┬───────────┘
                                     │
                        ┌────────────┴────────────┐
                        │                         │
                        ▼                         ▼
                客户发送                   Kefu发送
                        │                         │
                        ▼                         ▼
              移出队列                   检查空闲时长
                        │                         │
                        │                         ▼
                        │              ┌────────────────────┐
                        │              │ 超过阈值?           │
                        │              └─────────┬──────────┘
                        │                        │
                        │            ┌───────────┴──────────┐
                        │            │ 是                   │ 否
                        │            ▼                       ▼
                        │    ┌───────────────┐      ┌───────────────┐
                        │    │ 检查黑名单     │      │ 跳过（未达阈值）│
                        │    └───────┬───────┘      └───────────────┘
                        │            │
                        │            ▼
                        │    ┌────────────────────────────────┐
                        │    │ BlacklistChecker.is_blacklisted()│
                        │    └────────────────┬───────────────┘
                        │            │
                        │    ┌───────┴────────┐
                        │    │ 黑名单         │ 非黑名单
                        │    ▼                ▼
                        │    ┌───────────┐  ┌───────────┐
                        │    │ ⛔ 跳过    │  │ ✅ 加入队列│
                        │    └───────────┘  └───────────┘
                        │
                        ▼
              ┌───────────────────┐
              │ 更新队列状态       │
              │ 统计处理结果       │
              └───────────────────┘
```

## 日志示例

### 实时回复检测 - 黑名单用户被跳过

## 日志示例

### 黑名单用户被跳过

```
[DEVICE123] [1] 🔴 Processing: 张三 (queue: 5 remaining)
[DEVICE123] Processing: 张三
[DEVICE123]    - Unread count: 1
[DEVICE123] ⛔ Skipping blacklisted user: 张三
```

### 用户删除自动加入黑名单

```
[DEVICE123] 🚫 Detected user deletion message: 消息已发出，但被对方拒收了。
[DEVICE123] ✅ Automatically added 李四 to blacklist
```

### 新用户自动记录

```
[DEVICE123] Auto-added user to blacklist table (allowed): 王五 on DEVICE123
```

### 补刀队列管理 - 黑名单用户被跳过

```
[AN2FVB1706003302] [QueueMgr] ┌────────────────────────────────────────────────┐
[AN2FVB1706003302] [QueueMgr] │ 补刀队列: 处理对话列表                            │
[AN2FVB1706003302] [QueueMgr] └────────────────────────────────────────────────┘
[AN2FVB1706003302] [QueueMgr]   输入对话数: 15
[AN2FVB1706003302] [QueueMgr]   补刀配置:
[AN2FVB1706003302] [QueueMgr]     - 空闲阈值: 30 分钟
[AN2FVB1706003302] [QueueMgr]     - 最大补刀次数: 3
[AN2FVB1706003302] [QueueMgr]   处理每个对话:
[AN2FVB1706003302] [QueueMgr]     [1/15] 张三
[AN2FVB1706003302] [QueueMgr]       - 最后消息发送方: kefu
[AN2FVB1706003302] [QueueMgr]       - 最后消息时间: 2026-02-05 12:30:00
[AN2FVB1706003302] [QueueMgr]       - 队列状态: 无
[AN2FVB1706003302] [QueueMgr]       - 空闲时长: 45 分钟
[AN2FVB1706003302] [QueueMgr]       - 超过阈值 (30分钟)
[AN2FVB1706003302] [QueueMgr]       ⛔ 黑名单用户，跳过入队
[AN2FVB1706003302] [QueueMgr]     [2/15] 李四
[AN2FVB1706003302] [QueueMgr]       - 最后消息发送方: kefu
[AN2FVB1706003302] [QueueMgr]       - 空闲时长: 60 分钟
[AN2FVB1706003302] [QueueMgr]       - 超过阈值 (30分钟)
[AN2FVB1706003302] [QueueMgr]       ✅ 加入补刀队列 (空闲 60 分钟)
[AN2FVB1706003302] [QueueMgr]   ┌────────────────────────────────────────────────┐
[AN2FVB1706003302] [QueueMgr]   │ 处理结果统计                                    │
[AN2FVB1706003302] [QueueMgr]   ├────────────────────────────────────────────────┤
[AN2FVB1706003302] [QueueMgr]   │  新增入队: 8                                    │
[AN2FVB1706003302] [QueueMgr]   │  移出队列: 2                                    │
[AN2FVB1706003302] [QueueMgr]   │  已在队列(跳过): 3                              │
[AN2FVB1706003302] [QueueMgr]   │  对话继续(跳过): 1                              │
[AN2FVB1706003302] [QueueMgr]   │  未达阈值(跳过): 0                              │
[AN2FVB1706003302] [QueueMgr]   │  黑名单(跳过): 1                                │
[AN2FVB1706003302] [QueueMgr]   └────────────────────────────────────────────────┘
```

### 黑名单检查失败时的容错处理

```
[AN2FVB1706003302] [QueueMgr]     [3/15] 王五
[AN2FVB1706003302] [QueueMgr]       - 最后消息发送方: kefu
[AN2FVB1706003302] [QueueMgr]       - 空闲时长: 35 分钟
[AN2FVB1706003302] [QueueMgr]       - 超过阈值 (30分钟)
[AN2FVB1706003302] [QueueMgr]       ⚠️ 黑名单检查失败，继续入队判断: database is locked
[AN2FVB1706003302] [QueueMgr]       ✅ 加入补刀队列 (空闲 35 分钟)
```

## 缓存机制

为了提高性能，黑名单服务使用内存缓存：

```python
class BlacklistService:
    _cache: dict[str, Set[Tuple[str, Optional[str]]]] = {}
    _cache_loaded: bool = False

    @classmethod
    def load_cache(cls) -> None:
        """加载黑名单到内存缓存"""
        # 只加载 is_blacklisted=1 的记录
        cursor.execute("""
            SELECT device_serial, customer_name, customer_channel
            FROM blacklist
            WHERE is_blacklisted = 1
        """)
        ...

    @classmethod
    def invalidate_cache(cls) -> None:
        """清除缓存（在添加/删除后调用）"""
        cls._cache.clear()
        cls._cache_loaded = False
```

## 注意事项

1. **缓存一致性**: 添加/删除黑名单后会自动清除缓存
2. **渠道处理**: 同一用户名可能来自不同渠道，需要组合判断
3. **跳过追踪**: 被跳过的用户会记录在 `skipped_names` 中，不会被重复处理
4. **新红点检测**: 重新检测红点时，跳过的用户不会被重新加入队列

## 相关文件

| 文件                                                                   | 描述                       |
| ---------------------------------------------------------------------- | -------------------------- |
| `wecom-desktop/backend/services/blacklist_service.py`                  | 黑名单服务实现             |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 补刀响应检测器（实时回复） |
| `wecom-desktop/backend/servic../03-impl-and-arch/queue_manager.py`     | 补刀队列管理器（定时补刀） |
| `wecom-desktop/backend/routers/blacklist.py`                           | 黑名单 API 路由            |
| `src/wecom_automation/services/blacklist_service.py`                   | 底层黑名单检查器           |
| `src/wecom_automation/database/schema.py`                              | 数据库 schema 定义         |

## 参考文档

- [黑名单系统后端设计](blacklist-system-backend.md)
- [补刀系统逻辑文档](../03-impl-and-arch/followup-system-logic.md)
- [补刀搜索按钮 Resource ID 检测](./2026-02-05-followup-search-button-resource-id-detection.md)
- [补刀搜索输入框检测](./2026-02-04-followup-search-input-improvement.md)
