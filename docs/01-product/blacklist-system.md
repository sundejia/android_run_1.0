# 黑名单系统设计文档

> **最后更新**: 2026-04-04
> **状态**: ✅ 已实现 - 统一实现架构 + 名称匹配优化

## 概述

黑名单系统用于管理不希望被自动跟进或同步的用户。系统采用**统一实现架构**，所有黑名单操作通过 `src/wecom_automation/services/blacklist_service.py` 中的 `BlacklistChecker` 和 `BlacklistWriter` 类完成。

## 架构设计

### 统一服务层

黑名单服务采用**读写分离**设计：

```python
# src/wecom_automation/services/blacklist_service.py

# 查询类 - 类方法，无状态，用于高频检查
class BlacklistChecker:
    @classmethod
    def is_blacklisted(cls, device_serial, customer_name, customer_channel=None, use_cache=False) -> bool
    @classmethod
    def load_cache(cls) -> None
    @classmethod
    def invalidate_cache(cls) -> None

# 写入类 - 实例方法，需要 db_path，用于所有写操作
class BlacklistWriter:
    def __init__(self, db_path=None)
    def is_blacklisted_by_name(self, device_serial, customer_name) -> bool
    def add_to_blacklist(self, device_serial, customer_name, customer_channel=None, reason=None, deleted_by_user=False) -> bool
    def remove_from_blacklist(self, device_serial, customer_name, customer_channel=None) -> bool
    def upsert_scanned_users(self, device_serial, users_list) -> dict
    def get_whitelist(self, device_serial) -> Set[Tuple[str, Optional[str]]]
    def ensure_user_in_blacklist_table(self, device_serial, customer_name, customer_channel=None) -> bool
    def list_blacklist(self, device_serial=None) -> List[dict]
    def list_blacklist_with_status(self, device_serial=None) -> List[dict]
    def list_customers_with_status(self, device_serial, search=None, filter_type="all") -> List[dict]
    def update_status(self, entry_id, is_blacklisted) -> bool
    def batch_update_status(self, entry_ids, is_blacklisted) -> dict
```

### 调用关系

```
┌────────────────────────────────────────────────────────────────┐
│               Blacklist Service (Unified)                     │
│     src/wecom_automation/services/blacklist_service.py        │
└──────────────────────────────┬─────────────────────────────────┘
                               │
           ┌───────────────────┼───────────────────────┐
           │                   │                       │
           ▼                   ▼                       ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ BlacklistChecker │  │ BlacklistWriter  │  │  Cache Layer     │
│ (classmethod)    │  │ (instance)       │  │  _cache dict     │
└──────────────────┘  └──────────────────┘  └──────────────────┘
           │                   │                       │
           │                   │                       │
           ▼                   ▼                       ▼
  运行时黑名单检查      所有写操作和列表查询            内存缓存
  - Sync 流程         - 添加/移除黑名单                - 加载/清除
  - FollowUp 流程     - 批量操作
  - Response Detect  - 状态查询
```

### 调用者

**Python 框架层**:

- `sync_service.py` - `BlacklistChecker.is_blacklisted()` 跳过黑名单用户
- `orchestrator.py` - `BlacklistChecker.is_blacklisted()` + `BlacklistWriter.uperset/whitelist`
- `customer_syncer.py` - `BlacklistWriter.add_to_blacklist()` 自动拉黑
- `services/media_actions/actions/auto_blacklist.py` - 客户发送图片/视频后自动拉黑（配置见 [Media Auto-Actions](../features/media-auto-actions.md)）
- `queue_manager.py` - `BlacklistChecker.is_blacklisted()` 补刀队列检查

**Desktop Backend 层**:

- `routers/blacklist.py` - 所有黑名单 API 端点
- `routers/email.py` - 邮件通知相关黑名单操作
- `services/followup/response_detector.py` - 自动拉黑检测

## 数据库设计

### 表结构

```sql
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_channel TEXT,
    reason TEXT,
    deleted_by_user BOOLEAN DEFAULT 0,
    is_blacklisted BOOLEAN DEFAULT 1,        -- v7 新增：状态标识
    avatar_url TEXT,                         -- v7 新增：头像 URL
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(device_serial, customer_name, customer_channel)
);

CREATE INDEX IF NOT EXISTS idx_blacklist_device ON blacklist(device_serial);
CREATE INDEX IF NOT EXISTS idx_blacklist_name ON blacklist(customer_name);
CREATE INDEX IF NOT EXISTS idx_blacklist_status ON blacklist(is_blacklisted);
```

### 关键设计

1. **软删除策略**: `remove_from_blacklist()` 使用 UPDATE `is_blacklisted=0` 而非 DELETE，保留记录防止下次扫描时误判为新用户
2. **唯一约束**: `(device_serial, customer_name, customer_channel)` 组合唯一，防止重复记录
3. **状态字段**: `is_blacklisted` 字段支持切换黑名单/白名单状态，无需删除记录

## 后端 API 设计

### 端点列表

| 方法 | 路径                                   | 说明                                               |
| ---- | -------------------------------------- | -------------------------------------------------- |
| GET  | `/blacklist`                           | 获取黑名单列表（支持 `show_all` 参数显示所有记录） |
| GET  | `/blacklist/customers`                 | 获取设备所有用户及其黑名单状态                     |
| POST | `/blacklist/add`                       | 添加用户到黑名单                                   |
| POST | `/blacklist/remove`                    | 从黑名单移除用户（UPDATE is_blacklisted=0）        |
| GET  | `/blacklist/check`                     | 检查用户是否在黑名单中                             |
| POST | `/blacklist/toggle`                    | 切换用户黑名单状态                                 |
| POST | `/blacklist/batch-add`                 | 批量添加到黑名单                                   |
| POST | `/blacklist/batch-remove`              | 批量从黑名单移除                                   |
| POST | `/blacklist/upsert-scanned`            | 批量插入扫描用户（同步第一阶段）                   |
| GET  | `/blacklist/whitelist/{device_serial}` | 获取白名单用户列表（同步第二阶段）                 |
| POST | `/blacklist/update-status`             | 更新单个黑名单条目状态                             |
| POST | `/blacklist/batch-update-status`       | 批量更新黑名单状态                                 |

### 请求/响应模型

```python
class BlacklistEntry(BaseModel):
    id: int
    device_serial: str
    customer_name: str
    customer_channel: Optional[str] = None
    reason: Optional[str] = None
    deleted_by_user: bool = False
    is_blacklisted: bool = True
    avatar_url: Optional[str] = None
    created_at: str
    updated_at: str

class BlacklistAddRequest(BaseModel):
    device_serial: str
    customer_name: str
    customer_channel: Optional[str] = None
    reason: Optional[str] = None
    deleted_by_user: bool = False

class CustomerWithBlacklistStatus(BaseModel):
    customer_name: str
    customer_channel: Optional[str] = None
    is_blacklisted: bool
    blacklist_reason: Optional[str] = None
    deleted_by_user: bool = False
    last_message_at: Optional[str] = None
    message_count: int = 0
```

## 核心功能

### 1. 运行时黑名单检查

**设计原则**: 默认实时查询数据库，支持缓存模式

```python
# 默认实时查询（适合多进程场景）
is_blacklisted = BlacklistChecker.is_blacklisted(
    device_serial="ABC123",
    customer_name="张三",
    customer_channel="@WeChat",
    use_cache=False  # 默认值
)

# 缓存模式（适合批量操作）
is_blacklisted = BlacklistChecker.is_blacklisted(
    device_serial="ABC123",
    customer_name="张三",
    customer_channel="@WeChat",
    use_cache=True
)
```

**为什么默认实时查询**？

- Desktop backend 在主进程中修改黑名单（通过 API）
- Sync/followup 在子进程中检查黑名单
- 缓存无法跨进程共享，实时查询保证一致性

### 2. 黑名单写入操作

**Upsert 语义**:

- `add_to_blacklist()`: 如果记录已存在（即使 `is_blacklisted=0`），更新为 `is_blacklisted=1`
- `remove_from_blacklist()`: UPDATE `is_blacklisted=0`，不删除记录
- `upsert_scanned_users()`: 批量插入新用户，更新已存在用户的 `avatar_url`

**副作用**:

- 添加到黑名单时，自动清理 `followup_attempts` 表中的 pending 记录
- 记录操作日志到 metrics 系统

### 3. 同步流程集成

**Phase 1 - 扫描阶段**（`initial_sync.py`）:

```python
# 将所有扫描到的用户写入 blacklist 表，默认放行
writer.upsert_scanned_users(
    device_serial=device_serial,
    users_list=[{
        "customer_name": "张三",
        "customer_channel": "@WeChat",
        "avatar_url": "...",
        "reason": "Auto Scan"
    }]
)
# 新用户 is_blacklisted=0（默认放行）
```

**Phase 2 - 同步阶段**（`CustomerSyncer`）:

```python
# 获取允许同步的用户列表
whitelist = writer.get_whitelist(device_serial)
for customer_name, customer_channel in whitelist:
    # 仅同步白名单用户
    await sync_customer(customer_name, customer_channel)
```

**Phase 3 - 同步中**（`CustomerSyncer._process_messages`）:

```python
# 检测用户删除时自动拉黑
if user_deleted:
    writer.add_to_blacklist(
        device_serial=device_serial,
        customer_name=customer_name,
        customer_channel=customer_channel,
        reason="用户删除会话",
        deleted_by_user=True
    )
```

### 4. Follow-up 流程集成

**Queue Manager**（`queue_manager.py`）:

```python
# 生成补刀任务前检查黑名单
if BlacklistChecker.is_blacklisted(device_serial, customer_name, customer_channel):
    logger.info(f"跳过黑名单用户: {customer_name}")
    continue
```

**Response Detector**（`response_detector.py`）:

```python
# 检测到用户删除时自动拉黑
writer = BlacklistWriter()
writer.ensure_user_in_blacklist_table(device_serial, customer_name, customer_channel)
writer.add_to_blacklist(
    device_serial=device_serial,
    customer_name=customer_name,
    customer_channel=customer_channel,
    reason="用户删除会话",
    deleted_by_user=True
)
```

## 前端页面设计

### BlacklistView.vue

**功能**:

- 分设备显示所有聊天用户
- 支持用户名搜索
- 支持筛选（全部 / 已加入黑名单 / 未加入黑名单）
- 单个/批量添加/移除黑名单
- 显示用户消息统计

**路由配置**:

```javascript
{
  path: '/blacklist',
  name: 'Blacklist',
  component: () => import('@/views/BlacklistView.vue'),
  meta: { title: '黑名单管理' }
}
```

## 性能优化

### 1. 缓存策略

**内存缓存**:

```python
_cache: Dict[str, Set[Tuple[str, Optional[str]]]] = {}
# Key: device_serial
# Value: {(customer_name, customer_channel), ...}
```

**缓存加载**:

```python
BlacklistChecker.load_cache()
# 从数据库加载所有 is_blacklisted=1 的记录到内存
```

**缓存失效**:

```python
BlacklistChecker.invalidate_cache()
# 清除缓存（在写操作后调用）
```

### 2. 数据库索引

```sql
CREATE INDEX idx_blacklist_device ON blacklist(device_serial);
CREATE INDEX idx_blacklist_name ON blacklist(customer_name);
CREATE INDEX idx_blacklist_status ON blacklist(is_blacklisted);
```

### 3. 批量操作

- `upsert_scanned_users()` - 批量插入/更新用户
- `batch_update_status()` - 批量更新状态
- `batch-add` / `batch-remove` API 端点

## 重要行为说明

### 默认状态

新扫描的用户**默认放行**（`is_blacklisted=0`）:

- 符合"白名单优先"的设计原则
- 用户主动拉黑时才会设置为 `is_blacklisted=1`

### 状态切换

- **拉黑**: `add_to_blacklist()` → UPDATE `is_blacklisted=1`
- **放行**: `remove_from_blacklist()` → UPDATE `is_blacklisted=0`
- **切换**: `toggle` 端点 → 检测当前状态并反转

### 记录保留

`remove_from_blacklist()` **不删除记录**，仅更新状态:

- 防止下次扫描时误判为新用户
- 保留拉黑历史和原因

## 文件清单

| 文件                                                 | 类型 | 描述                     |
| ---------------------------------------------------- | ---- | ------------------------ |
| `src/wecom_automation/services/blacklist_service.py` | 核心 | 统一黑名单服务实现       |
| `wecom-desktop/backend/routers/blacklist.py`         | API  | 黑名单 API 端点          |
| `wecom-desktop/src/views/BlacklistView.vue`          | 前端 | 黑名单管理页面           |
| `scripts/cleanup_blacklisted_followup_attempts.py`   | 工具 | 清理黑名单用户的补刀记录 |

## 历史变更

### 2026-02-13: 名称优先匹配优化

**变更**: 黑名单检查和操作现在仅基于 `customer_name`，忽略 `customer_channel` 的差异

**原因**:

- Sidecar 视图（会话详情页）和消息列表视图的 channel 显示可能不一致
- 例如：消息列表显示 `@微信`，会话详情显示 `＠微信`（全角 @ 符号）
- 这导致同一用户在不同视图中被误判为不同用户

**修复内容**:

- 新增 `_normalize_channel()` 函数处理全角/半角 @ 符号转换
- `BlacklistChecker.is_blacklisted()` 现在仅按名称匹配
- `BlacklistWriter.add_to_blacklist()` 和 `remove_from_blacklist()` 也按名称匹配
- 新增单元测试 `tests/unit/test_blacklist_channel_matching.py`

**影响**:

- ✅ 解决跨视图渠道不一致导致的误判问题
- ✅ Sidecar 和主界面黑名单行为一致
- ⚠️ 同名不同用户可能被误判（业务上认为可接受，名称在业务逻辑中应唯一）

### 2026-02-06: 双套实现合并

**变更**: 删除 Desktop Backend 层的 `BlacklistService`，统一使用 Python 框架层的 `BlacklistChecker` + `BlacklistWriter`

**影响**:

- ✅ 消除行为不一致（`upsert_scanned_users` 默认值、`add_to_blacklist` 语义）
- ✅ 修复已知 bug（toggle 端点的 `reason` 字段、email 端点的废弃方法）
- ✅ 简化代码维护（单一实现，无重复逻辑）
- ✅ 增强功能（`add_to_blacklist` 现在包含 metrics 日志和补刀队列清理）

**详见**: `docs/03-impl-and-arch/key-modules/blacklist-dual-implementation-analysis.md`

## 注意事项

1. **多进程安全**: 默认实时查询数据库，不依赖缓存
2. **缓存一致性**: 写操作后调用 `BlacklistChecker.invalidate_cache()`
3. **重复检查**: 数据库 UNIQUE 约束防止重复记录
4. **渠道处理**: `customer_channel` 可为 None，组合 `(name, channel)` 唯一
5. **日志记录**: 记录黑名单相关操作日志用于调试
6. **名称优先匹配**: 黑名单检查仅基于 `customer_name`，忽略 `customer_channel` 的差异（修复不同视图渠道显示不一致导致的误判）

## 相关文档

- **实现分析**: `docs/03-impl-and-arch/key-modules/blacklist-dual-implementation-analysis.md`
- **数据库迁移**: `src/wecom_automation/database/migrations/`
- **API 文档**: `wecom-desktop/backend/routers/blacklist.py`
