# Blacklist 双套实现分析

> 分析日期: 2026-02-06  
> **状态: ✅ 已完成合并 (2026-02-06)**

## 概览

项目中**曾经**存在两套独立的 Blacklist 实现，现已合并为单一实现。

### 历史状态（合并前）

| 实现       | 文件路径                                              | 类名                                   | 所属层              | 状态          |
| ---------- | ----------------------------------------------------- | -------------------------------------- | ------------------- | ------------- |
| **实现 A** | `src/wecom_automation/services/blacklist_service.py`  | `BlacklistChecker` + `BlacklistWriter` | Python 自动化框架层 | ✅ 保留并扩展 |
| **实现 B** | `wecom-desktop/backend/services/blacklist_service.py` | `BlacklistService`                     | Desktop 后端 API 层 | ❌ 已删除     |

### 当前状态（合并后）

**统一实现**: `src/wecom_automation/services/blacklist_service.py`

- `BlacklistChecker` - 类方法，用于高频查询黑名单状态（支持实时DB查询和缓存模式）
- `BlacklistWriter` - 实例方法，用于所有写操作和列表查询

所有调用者（router、subprocess、scripts）现在统一使用这个实现。

---

## 1. 类结构对比

### 实现 A: BlacklistChecker + BlacklistWriter（框架层）

采用**读写分离**设计，两个类各司其职：

```
BlacklistChecker (classmethod-only, 无状态)
├── load_cache()           # 加载缓存
├── is_blacklisted()       # 检查黑名单（支持 use_cache 参数）
└── invalidate_cache()     # 清除缓存

BlacklistWriter (实例化, 需要 db_path)
├── upsert_scanned_users() # 批量 upsert 扫描用户
├── get_whitelist()        # 获取白名单
└── add_to_blacklist()     # 添加到黑名单
```

### 实现 B: BlacklistService（后端层）

采用**单一服务类**设计，读写混合：

```
BlacklistService (实例化 + classmethod 混合)
├── load_cache()                  # [classmethod] 加载缓存
├── is_blacklisted()              # [classmethod] 检查黑名单（纯缓存）
├── invalidate_cache()            # [classmethod] 清除缓存
├── add_to_blacklist()            # [instance] 添加到黑名单
├── remove_from_blacklist()       # [instance] 从黑名单移除（DELETE 操作）
├── list_blacklist()              # [instance] 列出黑名单
├── list_blacklist_with_status()  # [instance] 列出所有记录含状态
├── list_customers_with_status()  # [instance] 关联 customers 表查询
├── ensure_user_in_blacklist_table() # [instance] 确保用户存在
├── upsert_scanned_users()        # [instance] 批量 upsert
└── get_whitelist()               # [instance] 获取白名单
```

---

## 2. 关键行为差异

### 2.1 `is_blacklisted()` 查询策略

| 对比项           | 实现 A (BlacklistChecker)          | 实现 B (BlacklistService) |
| ---------------- | ---------------------------------- | ------------------------- |
| **默认模式**     | 实时查询数据库 (`use_cache=False`) | 纯缓存查询                |
| **缓存模式**     | `use_cache=True` 时使用缓存        | 始终使用缓存              |
| **降级策略**     | DB 查询失败 → 回退到缓存           | 无降级                    |
| **跨进程一致性** | ✅ 默认实时查询，适合多进程        | ❌ 缓存可能过期           |

**影响**：实现 A 专门为 Follow-up 模式下的多进程场景设计了实时查询（因为前端 Block 按钮在 backend API 进程中修改数据库，而 sync/followup 在子进程中检查）。实现 B 仅依赖缓存，若缓存未及时刷新则存在延迟。

### 2.2 `upsert_scanned_users()` 默认黑名单状态

| 对比项             | 实现 A (BlacklistWriter)              | 实现 B (BlacklistService)      |
| ------------------ | ------------------------------------- | ------------------------------ |
| **新用户默认状态** | `is_blacklisted=0`（默认放行/白名单） | `is_blacklisted=1`（默认拉黑） |

**这是一个严重的行为不一致**。在全量同步第一阶段扫描用户时：

- 实现 A：新扫描到的用户默认**允许同步**
- 实现 B：新扫描到的用户默认**被拉黑**

实际调用链中，`SyncOrchestrator` 和 `CustomerSyncer` 导入的是实现 A，因此**运行时行为以实现 A 为准**（默认放行）。但 API 端点 `/blacklist/upsert-scanned` 调用的是实现 B，如果通过 API 触发扫描则行为不同。

### 2.3 `add_to_blacklist()` 行为差异

| 对比项           | 实现 A (BlacklistWriter)  | 实现 B (BlacklistService)                     |
| ---------------- | ------------------------- | --------------------------------------------- |
| **记录已存在时** | UPDATE `is_blacklisted=1` | INSERT 触发 IntegrityError，返回 False        |
| **补刀队列清理** | ❌ 不清理                 | ✅ 清理 `followup_attempts` 中的 pending 记录 |
| **Metrics 日志** | ❌ 不记录                 | ✅ 通过 `metrics_logger` 记录                 |
| **Upsert 语义**  | ✅ 真正的 upsert          | ❌ 仅 insert，已存在视为失败                  |

**影响**：实现 A 的 `add_to_blacklist` 可以将一个之前被放行（`is_blacklisted=0`）的用户重新拉黑。实现 B 的版本则会因为 UNIQUE 约束冲突而失败——如果用户已经在表中（即使 `is_blacklisted=0`），也无法将其切换为拉黑。

### 2.4 `remove_from_blacklist()` 行为差异

| 对比项       | 实现 A                           | 实现 B                   |
| ------------ | -------------------------------- | ------------------------ |
| **实现方式** | ❌ **不存在此方法**              | ✅ DELETE FROM blacklist |
| **备注**     | 仅通过修改 `is_blacklisted` 字段 | 直接删除记录             |

**影响**：实现 B 的 `remove_from_blacklist` 使用 DELETE 操作会永久删除记录，而 API 端点 `/blacklist/update-status` 和 `/blacklist/batch-update-status` 则使用 UPDATE 方式（只修改 `is_blacklisted` 字段）。同一个后端内部存在矛盾：toggle 端点调用的 `remove_from_blacklist()` 会 DELETE 记录，而 `update-status` 端点只做 UPDATE。

### 2.5 独有功能

#### 仅实现 A 拥有的功能

无（实现 A 的功能在实现 B 中均有对应）

#### 仅实现 B 拥有的功能

| 方法                               | 说明                                     |
| ---------------------------------- | ---------------------------------------- |
| `remove_from_blacklist()`          | 删除黑名单记录                           |
| `list_blacklist()`                 | 列出黑名单（仅 `is_blacklisted=1`）      |
| `list_blacklist_with_status()`     | 列出所有记录（含 `is_blacklisted` 状态） |
| `list_customers_with_status()`     | 关联 `customers` 表，含消息统计          |
| `ensure_user_in_blacklist_table()` | 确保用户存在（默认 `is_blacklisted=0`）  |

---

## 3. 调用关系图

```
┌─────────────────────────────────────────────────────────────────────┐
│                   实现 A: BlacklistChecker / BlacklistWriter         │
│                 (src/wecom_automation/services/blacklist_service.py) │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────────┐
         │                     │                         │
         ▼                     ▼                         ▼
  sync_service.py     orchestrator.py           queue_manager.py
  (BlacklistChecker   (BlacklistChecker          (BlacklistChecker
   .is_blacklisted)    .is_blacklisted           .is_blacklisted)
                       BlacklistWriter
                       .upsert/whitelist)
         │                     │
         ▼                     ▼
  customer_syncer.py   response_detector.py
  (BlacklistWriter     (BlacklistChecker
   .add_to_blacklist)   .is_blacklisted)
                               │
                               │ 同时也调用 ▼
                        ┌──────┴───────────────────────────────────────┐
                        │                                              │
                        ▼                                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    实现 B: BlacklistService                          │
│              (wecom-desktop/backend/services/blacklist_service.py)   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
         ┌─────────────────────┼────────────────────┐
         │                     │                    │
         ▼                     ▼                    ▼
  blacklist.py (router)  email.py (router)   response_detector.py
  (全部 API 端点)         (_add_to_blacklist)  (.ensure_user_in_
                          (已废弃端点)          blacklist_table
                                                .add_to_blacklist)
```

### 特别注意: `response_detector.py` 混用两套实现

`response_detector.py` **同时导入并使用了两套实现**：

```python
# 顶层导入 - 实现 A
from wecom_automation.services.blacklist_service import BlacklistChecker

# 局部导入 - 实现 B
from services.blacklist_service import BlacklistService
```

- 使用 `BlacklistChecker.is_blacklisted()` 做运行时判断
- 使用 `BlacklistService().ensure_user_in_blacklist_table()` 做数据写入
- 使用 `BlacklistService().add_to_blacklist()` 做自动拉黑（检测用户删除时）

---

## 4. Bug 和潜在问题

### 4.1 `toggle` 端点引用不存在的字段

`blacklist.py` 路由中的 toggle 端点：

```python
reason=request.reason or "Toggled via Sidecar",
```

但 `BlacklistToggleRequest` 模型**没有 `reason` 字段**，这会在运行时抛出 `AttributeError`。

### 4.2 `email.py` 调用不存在的方法

```python
service = BlacklistService()
users = service.get_all_blacklisted()     # ❌ 方法不存在
service.remove_from_blacklist_by_name(...)  # ❌ 方法不存在
```

这两个方法在 `BlacklistService` 中未实现，调用会抛出 `AttributeError`。虽然注释标记为 deprecated，但代码依然存在且没有被真正废弃。

### 4.3 `upsert_scanned_users` 默认值不一致

如上述 2.2 节所述，两套实现对新用户的默认 `is_blacklisted` 值不一致（A=0, B=1）。这可能导致通过不同入口扫描用户时产生不同的行为。

### 4.4 `add_to_blacklist` 在实现 B 中无法处理已存在的白名单用户

实现 B 使用 INSERT + IntegrityError 捕获，当用户已在表中（`is_blacklisted=0`）时无法将其更新为 `is_blacklisted=1`，只会返回 False。

### 4.5 缓存为类变量，跨进程不共享

两套实现的缓存都是类变量（`_cache`），在多进程架构中（backend 是一个进程，sync/followup 子进程是另一个），缓存不共享。实现 A 通过默认实时查询 DB 解决了这个问题，实现 B 没有。

---

## 5. 数据库表 Schema

blacklist 表经过 v6→v7 迁移后，包含以下字段：

| 字段               | 类型              | 说明                        |
| ------------------ | ----------------- | --------------------------- |
| `id`               | INTEGER PK        | 自增主键                    |
| `device_serial`    | TEXT NOT NULL     | 设备序列号                  |
| `customer_name`    | TEXT NOT NULL     | 用户名                      |
| `customer_channel` | TEXT              | 渠道 (如 @WeChat)           |
| `reason`           | TEXT              | 加入原因                    |
| `deleted_by_user`  | BOOLEAN DEFAULT 0 | 是否因用户删除而加入        |
| `is_blacklisted`   | BOOLEAN DEFAULT 1 | 黑名单状态 (v7 新增)        |
| `avatar_url`       | TEXT              | 头像 URL (v7 新增)          |
| `created_at`       | TIMESTAMP         | 创建时间                    |
| `updated_at`       | TIMESTAMP         | 更新时间 (trigger 自动维护) |

唯一约束: `UNIQUE(device_serial, customer_name, customer_channel)`

---

## 6. 合并建议

### 方案一：统一为实现 A（推荐）

**理由**：实现 A 的读写分离设计更清晰，`is_blacklisted()` 支持实时查询更适合多进程场景。

**步骤**：

1. 将实现 B 独有的方法（`list_*`、`ensure_user_in_blacklist_table`、`remove_from_blacklist`）移入实现 A
2. 统一 `upsert_scanned_users` 的默认行为（建议默认 `is_blacklisted=0`，即放行）
3. 修复实现 B 的 `add_to_blacklist` 为 upsert 语义
4. 后端 router 改为导入实现 A 的类
5. 删除实现 B

### 方案二：保留两套，明确边界

**理由**：减少改动风险，各层维护自己的实现。

**步骤**：

1. 对齐行为差异（尤其是 `upsert_scanned_users` 默认值）
2. 修复已知 bug（toggle 的 reason、email 的废弃方法）
3. 明确文档：框架层用实现 A，API 层用实现 B，禁止混用
4. `response_detector.py` 中统一使用一套

### 方案三：抽取公共基类

**理由**：保留各自特色，消除重复代码。

**步骤**：

1. 创建 `BlacklistBase` 基类，包含缓存、DB 连接、核心查询逻辑
2. `BlacklistChecker`/`BlacklistWriter` 继承并保持框架层特性
3. `BlacklistService` 继承并保持 API 层特性
4. 统一行为差异

---

## 7. 合并执行记录

### 执行日期

2026-02-06

### 执行方案

选择了**方案一：统一为实现 A**

### 变更清单

1. **扩展 Implementation A** (`src/wecom_automation/services/blacklist_service.py`)
   - 添加 `remove_from_blacklist()` - 使用 UPDATE `is_blacklisted=0` (不 DELETE)
   - 添加 `ensure_user_in_blacklist_table()` - 确保用户存在（默认放行）
   - 添加 `list_blacklist()` - 列出 `is_blacklisted=1` 的记录
   - 添加 `list_blacklist_with_status()` - 列出所有记录含状态
   - 添加 `list_customers_with_status()` - 关联 customers 表查询
   - 添加 `update_status()` - 单条更新
   - 添加 `batch_update_status()` - 批量更新
   - 增强 `add_to_blacklist()` - 添加 metrics 日志 + 补刀队列清理

2. **更新 Backend Router** (`wecom-desktop/backend/routers/blacklist.py`)
   - 导入改为 `from wecom_automation.services.blacklist_service import BlacklistChecker, BlacklistWriter`
   - 所有 `BlacklistService()` → `BlacklistWriter()`
   - 所有 `BlacklistService.is_blacklisted()` → `BlacklistChecker.is_blacklisted()`
   - 所有 `BlacklistService.invalidate_cache()` → `BlacklistChecker.invalidate_cache()`
   - 替换 `_connection()` 直接访问为调用新增的 `update_status()` / `batch_update_status()` 方法
   - 修复 toggle 端点 bug（移除不存在的 `request.reason` 引用）
   - 修正 `upsert_scanned_users` 注释（默认 `is_blacklisted=0`）

3. **更新 Response Detector** (`wecom-desktop/backend/services/followup/response_detector.py`)
   - 替换局部导入 `from services.blacklist_service import BlacklistService` → `from wecom_automation.services.blacklist_service import BlacklistWriter`
   - `BlacklistService().ensure_user_in_blacklist_table()` → `BlacklistWriter().ensure_user_in_blacklist_table()`
   - `BlacklistService().add_to_blacklist()` → `BlacklistWriter().add_to_blacklist()`

4. **更新 Email Router** (`wecom-desktop/backend/routers/email.py`)
   - 导入改为 `from wecom_automation.services.blacklist_service import BlacklistChecker, BlacklistWriter`
   - 更新 `_add_to_blacklist()` 辅助函数使用 `BlacklistChecker` + `BlacklistWriter`
   - 删除两个废弃端点（`GET /blacklist`, `DELETE /blacklist/{customer_name}`）

5. **更新 Cleanup Script** (`scripts/cleanup_blacklisted_followup_attempts.py`)
   - 移除未使用的 `BlacklistService` 导入（脚本仅使用原始 SQL）

6. **删除 Implementation B**
   - 删除 `wecom-desktop/backend/services/blacklist_service.py`

### 行为变更

| 行为                                | 合并前                                               | 合并后                                       |
| ----------------------------------- | ---------------------------------------------------- | -------------------------------------------- |
| `upsert_scanned_users` 新用户默认值 | 实现A: `is_blacklisted=0`, 实现B: `is_blacklisted=1` | 统一为 `is_blacklisted=0`（默认放行）        |
| `add_to_blacklist` 已存在记录       | 实现A: UPDATE, 实现B: IntegrityError                 | 统一为 UPDATE（upsert 语义）                 |
| `add_to_blacklist` 副作用           | 实现A: 无, 实现B: 清理补刀+metrics                   | 统一添加副作用（metrics + 补刀清理）         |
| `remove_from_blacklist`             | 实现A: 不存在, 实现B: DELETE                         | 统一为 UPDATE `is_blacklisted=0`（保留记录） |
| `is_blacklisted` 查询策略           | 实现A: 实时DB查询, 实现B: 纯缓存                     | 保持实现A（支持 `use_cache` 参数）           |

### Bug 修复

1. **Toggle 端点 bug** - 移除了对不存在字段 `request.reason` 的引用
2. **Email 端点 bug** - 删除了调用不存在方法的两个废弃端点

## 8. 总结（历史记录）

| 维度        | 实现 A (框架层)             | 实现 B (后端层)                        |
| ----------- | --------------------------- | -------------------------------------- |
| 设计模式    | 读写分离 (Checker + Writer) | 单一服务类                             |
| 代码行数    | ~395 行                     | ~652 行                                |
| 功能完整度  | 核心功能 (查/写/upsert)     | 完整 CRUD + 查询                       |
| 多进程安全  | ✅ 默认实时查询 DB          | ❌ 纯缓存可能过期                      |
| upsert 默认 | `is_blacklisted=0` (放行)   | `is_blacklisted=1` (拉黑)              |
| add 语义    | Upsert (已存在则 UPDATE)    | Insert-only (已存在则失败)             |
| remove 方式 | 无此方法                    | DELETE 记录                            |
| 副作用      | 无                          | 清理补刀队列 + Metrics                 |
| 调用者      | sync、orchestrator、子进程  | router、response_detector              |
| 已知 bug    | 无                          | toggle 缺 reason、email 调用不存在方法 |

**核心风险**：`response_detector.py` 同时混用两套实现，行为不一致可能导致难以排查的问题。建议优先统一为一套实现，或至少对齐关键行为差异。
