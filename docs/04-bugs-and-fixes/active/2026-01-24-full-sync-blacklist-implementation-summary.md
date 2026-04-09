# 全量同步 Blacklist 集成实现总结

**日期**: 2026-01-24
**实施方案**: 方案 A - 在 SyncOrchestrator 中修复

---

## 修改的文件

### 1. `src/wecom_automation/services/blacklist_service.py`

**修改内容**: 添加 `BlacklistWriter` 类

```python
class BlacklistWriter:
    """Blacklist writer for sync framework."""

    def upsert_scanned_users(
        self,
        device_serial: str,
        users_list: List[Dict[str, any]],
    ) -> Dict[str, int]:
        """
        批量处理扫描到的用户（Upsert 操作）

        - 新记录：插入并设置 is_blacklisted=1（默认拉黑）
        - 已存在：更新 avatar_url，保持原 is_blacklisted 状态
        """

    def get_whitelist(self, device_serial: str) -> Set[Tuple[str, Optional[str]]]:
        """
        获取白名单用户（is_blacklisted=0）

        用于 Phase 2 过滤出允许同步的用户
        """
```

**新增功能**:

- `upsert_scanned_users()`: 批量写入用户到 blacklist 表
- `get_whitelist()`: 从 blacklist 表读取白名单用户
- 自动缓存失效机制（调用 `BlacklistChecker.invalidate_cache()`）

---

### 2. `src/wecom_automation/services/sync/orchestrator.py`

#### 修改 1: `_get_customers()` 方法 (第 707-775 行)

**新增逻辑** (第 729-768 行):

```python
# === 新增：将扫描到的用户写入 blacklist 表 ===
try:
    from wecom_automation.services.blacklist_service import BlacklistWriter

    device_serial = self._wecom.device_serial if hasattr(self._wecom, 'device_serial') else ""
    if not device_serial:
        self._logger.warning("No device serial available, skipping blacklist upsert")
    else:
        blacklist_writer = BlacklistWriter()

        # 转换为 upsert_scanned_users 需要的格式
        users_list = []
        for user in users:
            users_list.append({
                "customer_name": getattr(user, 'name', str(user)),
                "customer_channel": getattr(user, 'channel', None),
                "avatar_url": None,
                "reason": "Auto Scan",
            })

        result = blacklist_writer.upsert_scanned_users(device_serial, users_list)

        self._logger.info(
            f"✅ Blacklist Phase 1 Complete: "
            f"{result['inserted']} new users (blocked), "
            f"{result['updated']} existing users (status preserved)"
        )

        # 提示用户需要在黑名单管理页面放行用户
        if result['inserted'] > 0:
            self._logger.info(
                f"📋 {result['inserted']} new users added to blacklist (default blocked). "
                f"Use the blacklist management page to unblock users before syncing."
            )

except Exception as e:
    self._logger.error(f"Failed to upsert scanned users to blacklist: {e}")
# === 新增结束 ===
```

**功能**:

- Phase 1 完成后，自动将所有扫描到的用户写入 blacklist 表
- 新用户默认 `is_blacklisted=1`（拉黑状态）
- 已存在用户保持原状态（尊重用户之前的设置）

---

#### 修改 2: `run()` 方法 Phase 1.5 (第 141-187 行)

**新增逻辑**:

```python
# =========================================================
# Phase 1.5: 从 blacklist 表读取白名单用户
# =========================================================
# 只有在用户主动放行后（is_blacklisted=0），用户才会被同步
self._logger.info("Phase 1.5: Filtering whitelisted users from blacklist table...")
try:
    from wecom_automation.services.blacklist_service import BlacklistWriter

    device_serial = self._wecom.device_serial if hasattr(self._wecom, 'device_serial') else ""
    if device_serial:
        blacklist_writer = BlacklistWriter()
        whitelist = blacklist_writer.get_whitelist(device_serial)

        # 过滤出白名单用户（is_blacklisted=0）
        whitelisted_customers = []
        for customer in customers:
            name = getattr(customer, 'name', str(customer))
            channel = getattr(customer, 'channel', None)
            if (name, channel) in whitelist:
                whitelisted_customers.append(customer)

        self._logger.info(
            f"📋 Filtered to {len(whitelisted_customers)} whitelisted users "
            f"(out of {len(customers)} total scanned)"
        )

        customers = whitelisted_customers
        self._progress.total_customers = len(customers)

        if len(customers) == 0 and self._progress.total_customers > 0:
            self._logger.warning(
                "⚠️ No whitelisted users found! All users are blocked by default. "
                "Use the blacklist management page to unblock users before syncing."
            )

except Exception as e:
    self._logger.error(f"Failed to filter whitelisted users: {e}")
    # 如果过滤失败，继续使用所有用户（向后兼容）
    self._logger.info("⚠️ Whitelist filtering failed, syncing all scanned users")
```

**功能**:

- Phase 1 和 Phase 2 之间新增过滤步骤
- 从 blacklist 表读取 `is_blacklisted=0` 的用户
- 只同步白名单用户，跳过默认拉黑的用户

---

## 新的同步流程

```
┌─────────────────────────────────────────────────────────────┐
│                    全量同步流程（更新后）                    │
└─────────────────────────────────────────────────────────────┘

Phase 1: Robust User Extraction
  ↓
  滚动列表，提取所有用户
  ↓
  ✅ 调用 BlacklistWriter.upsert_scanned_users()
     - 新用户 → 插入 blacklist 表 (is_blacklisted=1)
     - 已存在 → 更新头像，保持原状态
  ↓
  "Found N total customers"
  ↓
Phase 1.5: Whitelist Filtering (NEW!)
  ↓
  ✅ 调用 BlacklistWriter.get_whitelist()
     - 读取 is_blacklisted=0 的用户
  ↓
  过滤出白名单用户
  ↓
  "Filtered to M whitelisted users (out of N total)"
  ↓
Phase 2: Sequential Sync
  ↓
  只同步白名单用户
  ↓
  完成
```

---

## 用户操作流程

### 首次全量同步

1. **运行同步**:

   ```bash
   uv run initial_sync_v2.py --serial ABC123
   ```

2. **Phase 1 完成**:

   ```
   ✅ Blacklist Phase 1 Complete: 150 new users (blocked), 0 existing users
   📋 150 new users added to blacklist (default blocked).
   ```

3. **Phase 1.5 完成**:

   ```
   📋 Filtered to 0 whitelisted users (out of 150 total scanned)
   ⚠️ No whitelisted users found! All users are blocked by default.
   ```

4. **同步结束**（没有用户被同步）

5. **用户操作**:
   - 打开桌面应用
   - 进入"黑名单管理"页面
   - 选择要同步的用户，取消勾选（设置 `is_blacklisted=0`）

6. **再次运行同步**:

   ```bash
   uv run initial_sync_v2.py --serial ABC123
   ```

7. **Phase 1.5 完成**:

   ```
   📋 Filtered to 10 whitelisted users (out of 150 total scanned)
   ```

8. **只同步这 10 个用户**

---

## 日志示例

### 首次同步（没有白名单用户）

```
18:30:00 | INFO     | Starting Phase 1: Robust User Extraction...
18:30:05 | INFO     | Getting customer list...
18:30:15 | INFO     | ✅ Blacklist Phase 1 Complete: 150 new users (blocked), 0 existing users (status preserved)
18:30:15 | INFO     | 📋 150 new users added to blacklist (default blocked). Use the blacklist management page to unblock users before syncing.
18:30:15 | INFO     | Phase 1 Complete. Found 150 total customers.
18:30:15 | INFO     | Phase 1.5: Filtering whitelisted users from blacklist table...
18:30:15 | INFO     | 📋 Filtered to 0 whitelisted users (out of 150 total scanned)
18:30:15 | WARNING  | ⚠️ No whitelisted users found! All users are blocked by default. Use the blacklist management page to unblock users before syncing.
18:30:15 | INFO     | Starting Phase 2: Sequential Sync...
18:30:15 | INFO     | Sync completed, 0 customers synced
```

### 第二次同步（有白名单用户）

```
18:35:00 | INFO     | Starting Phase 1: Robust User Extraction...
18:35:05 | INFO     | Getting customer list...
18:35:15 | INFO     | ✅ Blacklist Phase 1 Complete: 0 new users (blocked), 150 existing users (status preserved)
18:35:15 | INFO     | Phase 1 Complete. Found 150 total customers.
18:35:15 | INFO     | Phase 1.5: Filtering whitelisted users from blacklist table...
18:35:15 | INFO     | 📋 Filtered to 10 whitelisted users (out of 150 total scanned)
18:35:15 | INFO     | Starting Phase 2: Sequential Sync...
18:35:20 | INFO     | ▶️ Starting sync: 张三
18:35:30 | INFO     | ✅ Completed: 张三 | Messages: 5 added, 0 skipped
...
18:37:00 | INFO     | ✅ Queue empty, all whitelisted users processed
```

---

## 向后兼容性

- ✅ 如果过滤失败（异常），会继续使用所有用户（向后兼容）
- ✅ 没有设备序列号时，跳过过滤（向后兼容）
- ✅ `BlacklistChecker.is_blacklisted()` 仍然有效（检查 `is_blacklisted=1` 的用户）

---

## 下一步

### 待实现功能

1. **头像捕获**: 在扫描时捕获用户头像，存储到 `blacklist.avatar_url`
   - 位置: `orchestrator.py:745` (`avatar_url: None,  # TODO: 可以在扫描时捕获头像`)

2. **进度显示**: 在桌面应用中显示 Phase 1 和 Phase 1.5 的进度

3. **批量操作**: 在黑名单管理页面添加"全选"、"反选"等批量操作

4. **导入/导出**: 支持导出黑名单配置，方便备份

---

## 验证步骤

1. **运行首次同步**:

   ```bash
   uv run initial_sync_v2.py --serial YOUR_DEVICE_SERIAL
   ```

2. **检查数据库**:

   ```bash
   sqlite3 wecom_conversations.db "SELECT COUNT(*) FROM blacklist WHERE reason='Auto Scan';"
   # 应该看到扫描到的用户数量
   ```

3. **在桌面应用中放行用户**:
   - 打开桌面应用
   - 进入"黑名单管理"
   - 取消勾选要同步的用户

4. **再次运行同步**:

   ```bash
   uv run initial_sync_v2.py --serial YOUR_DEVICE_SERIAL
   ```

5. **验证只同步了白名单用户**:
   - 检查日志: "Filtered to N whitelisted users"
   - 检查数据库: `SELECT COUNT(*) FROM customers WHERE ...`

---

## 相关文件

- **问题分析**: `docs/04-bugs-and-fixes/active/01-24-full-sync-blacklist-not-writing.md`
- **设计文档**: `docs/sync-blacklist-selection-feature.md`
- **实现代码**:
  - `src/wecom_automation/services/blacklist_service.py`
  - `src/wecom_automation/services/sync/orchestrator.py`

---

## 状态

- [x] 添加 BlacklistWriter 类到 framework
- [x] 修改 \_get_customers() 添加 upsert 逻辑
- [x] 修改 run() Phase 2 添加白名单过滤
- [x] 语法检查通过
- [ ] 实际测试（需要设备）
- [ ] 更新桌面应用文档
