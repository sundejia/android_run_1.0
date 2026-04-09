# 全量同步未将用户写入 Blacklist 表问题分析

**日期**: 2026-01-24
**相关文件**:

- `src/wecom_automation/services/sync/orchestrator.py`
- `wecom-desktop/backend/services/blacklist_service.py`
- `initial_sync_v2.py`
- `docs/sync-blacklist-selection-feature.md`

---

## 问题描述

**用户期望**: 全量同步检索完用户列表后，将所有用户写入 blacklist 表，用户可以自行选择 block 哪一个。

**实际行为**: 全量同步获取了用户列表，但没有将用户写入 blacklist 表。

---

## 设计意图

根据 `docs/sync-blacklist-selection-feature.md`，全量同步应该使用 **Two-Phase Strategy**：

### Phase 1: Robust Extraction (索引构建)

1. 滚动列表到底部，捕获所有用户名/头像
2. 调用 `BlacklistService.upsert_scanned_users()` 将用户写入 blacklist 表
   - 新记录：插入并设置 `is_blacklisted=1`（默认拉黑）
   - 已存在：更新头像/时间，保持原 `is_blacklisted` 状态

### Phase 2: Sequential Sync (执行同步)

1. 读取 blacklist 表，过滤出 `is_blacklisted=0` 的用户（白名单）
2. 逐个进入详情页抓取数据

---

## 当前实现分析

### 1. SyncOrchestrator.\_get_customers()

**文件**: `src/wecom_automation/services/sync/orchestrator.py:707-734`

```python
async def _get_customers(self, options: SyncOptions) -> List[Any]:
    """获取待同步客户列表"""
    # ...

    # 提取用户列表
    users = []
    if hasattr(self._wecom, 'extract_private_chat_users'):
        result = await self._wecom.extract_private_chat_users()
        users = result.users if hasattr(result, 'users') else result
    # ...

    return users
```

**问题**: `_get_customers()` 只获取了用户列表，没有调用 `upsert_scanned_users()`。

### 2. SyncOrchestrator.run()

**文件**: `src/wecom_automation/services/sync/orchestrator.py:136-144`

```python
# Phase 1: 获取全量客户列表
self._logger.info("Starting Phase 1: Robust User Extraction...")
customers = await self._get_customers(options)
self._progress.total_customers = len(customers)
self._logger.info(f"Phase 1 Complete. Found {len(customers)} total customers.")

# Phase 2: 顺序同步
self._logger.info("Starting Phase 2: Sequential Sync...")
```

**问题**:

1. Phase 1 获取了客户列表，但没有将其写入 blacklist 表
2. Phase 2 直接使用 Phase 1 的客户列表进行同步，没有从 blacklist 表读取白名单用户

### 3. BlacklistService.upsert_scanned_users()

**文件**: `wecom-desktop/backend/services/blacklist_service.py:404-507`

这个方法已经实现，但从未被调用：

```python
def upsert_scanned_users(
    self,
    device_serial: str,
    users_list: List[Dict[str, any]],
) -> Dict[str, int]:
    """
    批量处理扫描到的用户（Upsert 操作）

    用于全量同步第一阶段：将所有扫描到的用户写入 blacklist 表。
    - 新记录：插入并设置 is_blacklisted=1（默认拉黑）
    - 已存在：更新 avatar_url，保持原 is_blacklisted 状态（尊重用户之前的选择）
    """
```

### 4. 缺少白名单过滤逻辑

全量同步应该只同步 `is_blacklisted=0` 的用户，但当前代码没有这个过滤：

```python
# 当前代码 (orchestrator.py:238-241)
if self._blacklist.is_blacklisted(customer_name, customer_channel):
    self._logger.info(f"⏭️ Skipping blacklisted user: {customer_name}")
    processed_names.add(customer_name)
    continue
```

这里的 `is_blacklisted()` 只检查 `is_blacklisted=1` 的用户，但问题是：

- 用户根本没有被写入 blacklist 表
- 所以这个检查实际上不起作用

---

## 根因总结

| 位置                                | 缺失的逻辑                                                               |
| ----------------------------------- | ------------------------------------------------------------------------ |
| `SyncOrchestrator._get_customers()` | 获取用户列表后，没有调用 `upsert_scanned_users()`                        |
| `SyncOrchestrator.run()`            | Phase 1 和 Phase 2 之间缺少 "写入 blacklist 表" 的步骤                   |
| `SyncOrchestrator.run()`            | Phase 2 应该从 blacklist 表读取白名单用户，而不是直接使用 Phase 1 的列表 |

---

## 修复方案

### 方案 A：在 SyncOrchestrator 中修复（推荐）

#### 1. 修改 `_get_customers()` 方法

```python
async def _get_customers(self, options: SyncOptions) -> List[Any]:
    """获取待同步客户列表"""
    # ... 现有代码获取 users ...

    # === 新增：写入 blacklist 表 ===
    try:
        from services.blacklist_service import BlacklistService
        blacklist_service = BlacklistService()

        # 转换为 upsert_scanned_users 需要的格式
        users_list = []
        for user in users:
            users_list.append({
                "customer_name": getattr(user, 'name', str(user)),
                "customer_channel": getattr(user, 'channel', None),
                "avatar_url": None,  # 可以在扫描时捕获
                "reason": "Auto Scan",
            })

        device_serial = self._wecom.device_serial if hasattr(self._wecom, 'device_serial') else ""
        result = blacklist_service.upsert_scanned_users(device_serial, users_list)

        self._logger.info(
            f"✅ Upserted {result['inserted']} new users, "
            f"updated {result['updated']} existing users to blacklist table"
        )
    except Exception as e:
        self._logger.error(f"Failed to upsert scanned users: {e}")
    # === 新增结束 ===

    return users
```

#### 2. 修改 `run()` 方法中的 Phase 2

在 Phase 2 开始时，从 blacklist 表读取白名单用户：

```python
# Phase 2: 从 blacklist 表读取白名单用户
self._logger.info("Starting Phase 2: Sequential Sync (whitelist only)...")

# === 新增：从 blacklist 表获取白名单用户 ===
try:
    from services.blacklist_service import BlacklistService
    blacklist_service = BlacklistService()

    device_serial = self._wecom.device_serial if hasattr(self._wecom, 'device_serial') else ""
    whitelist = blacklist_service.get_whitelist(device_serial)

    # 过滤出白名单用户
    whitelisted_customers = []
    for customer in customers:
        name = getattr(customer, 'name', str(customer))
        channel = getattr(customer, 'channel', None)
        if (name, channel) in whitelist:
            whitelisted_customers.append(customer)

    self._logger.info(
        f"📋 Filtered to {len(whitelisted_customers)} whitelisted users "
        f"(out of {len(customers)} total)"
    )

    customers = whitelisted_customers
    self._progress.total_customers = len(customers)
except Exception as e:
    self._logger.error(f"Failed to load whitelist, using all customers: {e}")
# === 新增结束 ===

# 使用队列处理客户（白名单）
customer_queue = deque(customers)
```

### 方案 B：创建独立的扫描阶段

创建一个独立的 `_scan_and_index_users()` 方法，明确区分扫描和同步：

```python
async def _scan_and_index_users(self, options: SyncOptions) -> List[Any]:
    """
    Phase 1: 扫描并索引所有用户到 blacklist 表

    这个阶段只做两件事：
    1. 滚动列表获取所有用户
    2. 将用户写入 blacklist 表（默认 is_blacklisted=1）
    """
    self._logger.info("Phase 1: Scanning and indexing all users...")

    # 1. 获取所有用户
    users = await self._get_all_users_from_scroll()

    # 2. 写入 blacklist 表
    await self._index_users_to_blacklist(users)

    return users

async def _sync_whitelisted_users(self, all_users: List[Any], options: SyncOptions):
    """
    Phase 2: 同步白名单用户

    从 blacklist 表读取 is_blacklisted=0 的用户并进行同步
    """
    self._logger.info("Phase 2: Syncing whitelisted users...")

    # 1. 读取白名单
    whitelist = self._get_whitelist_from_blacklist()

    # 2. 过滤并同步
    whitelisted_users = [u for u in all_users if self._is_whitelisted(u, whitelist)]

    # 3. 执行同步
    await self._sync_users_sequentially(whitelisted_users, options)
```

---

## 依赖问题

**注意**: `SyncOrchestrator` 在 `src/wecom_automation/` 中，而 `BlacklistService` 在 `wecom-desktop/backend/services/` 中。

需要解决导入路径问题：

```python
# 方案 1: 将 BlacklistService 移动到 src/wecom_automation/services/
# 方案 2: 在 wecom_automation 中创建一个代理类
# 方案 3: 动态导入（不推荐，但可以工作）
```

---

## 测试验证

修复后需要验证：

1. **Phase 1 验证**:

   ```sql
   -- 检查用户是否被写入
   SELECT COUNT(*) FROM blacklist WHERE reason = 'Auto Scan';
   ```

2. **Phase 2 验证**:

   ```sql
   -- 检查白名单用户是否被同步
   SELECT COUNT(*) FROM blacklist WHERE is_blacklisted = 0;
   ```

3. **端到端测试**:
   - 运行全量同步
   - 检查 blacklist 表是否有新用户（is_blacklisted=1）
   - 手动将一些用户设置为 is_blacklisted=0
   - 再次运行同步，确认只有白名单用户被处理

---

## 相关文档

- `docs/sync-blacklist-selection-feature.md` - 完整的功能设计文档
- `docs/sync-blacklist-selection-implementation-summary.md` - 实现总结
- `wecom-desktop/backend/routers/blacklist.py:317` - API 端点 `/blacklist/upsert-scanned`

---

## 状态

- [ ] 修复 `_get_customers()` 添加 upsert 逻辑
- [ ] 修复 `run()` Phase 2 添加白名单过滤
- [ ] 解决导入路径问题
- [ ] 添加日志和错误处理
- [ ] 编写测试用例
- [ ] 更新文档
