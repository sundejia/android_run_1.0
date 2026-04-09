# Bug: 补刀执行时未过滤黑名单用户

> **创建时间**: 2026-02-06  
> **修复时间**: 2026-02-06  
> **状态**: ✅ Fixed  
> **严重程度**: High  
> **影响范围**: 补刀系统（FollowUp Queue Manager）

## 问题描述

**用户反馈**：有多个用户反映，某些客户已经被加入黑名单，但仍然收到了自动补刀消息。

**预期行为**：黑名单中的用户应该在所有阶段都被过滤，包括：

1. ✅ 加入补刀队列时（已实现）
2. ✅ 实时回复检测时（已实现）
3. ❌ **执行补刀时（未实现）** ← 问题所在

**实际行为**：用户被加入黑名单后，如果数据库中已存在该用户的补刀队列记录，执行补刀时不会再次检查黑名单状态，导致黑名单用户仍被补刀。

## 根本原因分析

### 1. 补刀流程的两个关键阶段

```
┌──────────────────────────────────────────────────────────────────┐
│ Stage 1: 加入补刀队列 (process_conversations)                      │
│ ✅ 有黑名单检查                                                     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ followup_attempts │
                    │ 表中持久化存储    │
                    └────────┬───────┘
                             │
                             │ 用户被加入黑名单
                             │ ⚠️ 数据库中的补刀记录未清理
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ Stage 2: 执行补刀 (execute_pending_followups)                     │
│ ❌ 没有黑名单检查                                                   │
│ 直接从数据库读取 pending 记录并执行                                 │
└──────────────────────────────────────────────────────────────────┘
```

### 2. 代码分析

#### ✅ Stage 1: 加入队列时有黑名单检查

**文件**: `wecom-desktop/backend/services/followup/queue_manager.py`

```python
def process_conversations(self, conversations: list[ConversationInfo]) -> dict[str, Any]:
    """处理对话列表，更新补刀队列"""

    for idx, conv in enumerate(conversations, 1):
        # ... 其他检查 ...

        # ✅ 黑名单用户不进入补刀队列
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
            self._log(f"      ⚠️ 黑名单检查失败，继续入队判断: {e}", "WARN")

        # 加入队列
        repo.add_or_update(...)
```

#### ❌ Stage 2: 执行补刀时没有黑名单检查

**文件**: `wecom-desktop/backend/services/followup/queue_manager.py`

```python
async def execute_pending_followups(
    self,
    skip_check: Callable[[], bool] | None = None,
    ai_reply_callback: Callable[[str, str], Awaitable[str | None]] | None = None,
) -> dict[str, Any]:
    """执行待补刀任务"""

    # 获取待补刀列表
    pending = repo.get_pending_attempts(
        self.device_serial,
        limit=settings.max_followups,
        attempt_intervals=settings.attempt_intervals,
    )

    for idx, attempt in enumerate(pending, 1):
        # ❌ 没有黑名单检查！
        # 只检查中断信号
        if skip_check and skip_check():
            break

        # ❌ 直接生成消息并执行补刀
        message = await self._generate_message(...)
        result = await executor.execute(attempt.customer_name, message, skip_check)

        # 更新数据库
        if result.status == FollowupStatus.SUCCESS:
            repo.record_followup_sent(attempt.id, new_message_id)
```

### 3. 问题场景重现

#### 场景 A: 用户先进入队列，后被加入黑名单

```
时间线：
T1: 客户 "张三" 闲置 30 分钟
    → process_conversations() 检查黑名单: ❌ 不在黑名单
    → 加入补刀队列 (followup_attempts 表)

T2: 客服手动将 "张三" 加入黑名单
    → blacklist 表: is_blacklisted=1
    → ⚠️ followup_attempts 表中的记录未清理

T3: 执行补刀
    → execute_pending_followups() 从数据库读取 pending 记录
    → ❌ 没有再次检查黑名单
    → 补刀消息发送给 "张三" ← 问题！
```

#### 场景 B: 用户代码未更新（旧版本）

```
用户环境：
- 旧版本代码: process_conversations() 没有黑名单检查
- 数据库中已有大量 pending 记录

更新后：
- 新版本: process_conversations() 有黑名单检查
- 但旧记录仍在数据库中
- execute_pending_followups() 仍会执行旧记录
```

### 4. 数据库表对比

#### blacklist 表

```sql
SELECT * FROM blacklist WHERE customer_name = '张三';

-- Result:
-- id | device_serial | customer_name | is_blacklisted | created_at          | updated_at
-- 1  | ABC123        | 张三          | 1              | 2026-02-06 10:00:00 | 2026-02-06 10:00:00
```

#### followup_attempts 表（问题所在）

```sql
SELECT * FROM followup_attempts WHERE customer_name = '张三';

-- Result:
-- id | device_serial | customer_name | status  | current_attempt | created_at
-- 5  | ABC123        | 张三          | pending | 0               | 2026-02-05 15:00:00
-- ⚠️ 这条记录是在用户加入黑名单之前创建的，执行补刀时不会被过滤
```

## 影响范围

### 受影响的用户类型

1. **手动加入黑名单的用户** - 在加入黑名单之前已进入补刀队列
2. **自动加入黑名单的用户** - 如"用户删除/拉黑"检测后自动加入黑名单
3. **旧版本遗留数据** - 用户更新代码前已存在的补刀记录

### 影响程度

- **高**: 可能导致客户体验不佳（收到不应发送的自动消息）
- **高**: 可能触发客户投诉或拉黑
- **中**: 浪费 API 额度（AI 生成消息）
- **低**: 不影响系统稳定性，只影响业务逻辑

## 解决方案

### 方案 1: 执行补刀时添加黑名单过滤（推荐）

**优点**:

- ✅ 最安全，双重保险
- ✅ 兼容旧版本遗留数据
- ✅ 防止竞态条件（用户在队列检查和执行之间被加入黑名单）

**实现**:

```python
async def execute_pending_followups(
    self,
    skip_check: Callable[[], bool] | None = None,
    ai_reply_callback: Callable[[str, str], Awaitable[str | None]] | None = None,
) -> dict[str, Any]:
    """执行待补刀任务"""

    # ... 获取待补刀列表 ...

    results = {
        "executed": True,
        "total": len(pending),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "skipped_blacklisted": 0,  # 新增：黑名单跳过计数
        "details": [],
    }

    for idx, attempt in enumerate(pending, 1):
        self._log(f"  [{idx}/{len(pending)}] {attempt.customer_name}")

        # 检查中断信号
        if skip_check and skip_check():
            self._log("  ⛔ 收到中断信号，停止补刀")
            break

        # ✅ 新增：执行前再次检查黑名单
        try:
            from wecom_automation.services.blacklist_service import BlacklistChecker

            if BlacklistChecker.is_blacklisted(
                self.device_serial,
                attempt.customer_name,
                attempt.customer_id,  # 如果有 channel 信息
                use_cache=False,  # 不使用缓存，确保实时性
            ):
                self._log("  ⛔ 黑名单用户，跳过补刀")
                results["skipped"] += 1
                results["skipped_blacklisted"] += 1

                # 可选：将记录标记为 cancelled
                repo.cancel_attempt(attempt.id, reason="User is blacklisted")

                continue
        except Exception as e:
            # 黑名单检查失败时记录警告，但继续执行（避免阻断主流程）
            self._log(f"  ⚠️ 黑名单检查失败: {e}，继续执行补刀", "WARN")

        # 生成消息并执行补刀
        message = await self._generate_message(...)
        result = await executor.execute(...)

        # ... 更新数据库 ...
```

### 方案 2: 用户加入黑名单时清理补刀队列

**优点**:

- ✅ 主动清理，数据库更干净
- ✅ 减少执行时的检查开销

**缺点**:

- ❌ 无法处理旧版本遗留数据
- ❌ 需要修改多处代码（所有加入黑名单的入口）

**实现**:

```python
class BlacklistService:
    def add_to_blacklist(
        self,
        device_serial: str,
        customer_name: str,
        customer_channel: str | None = None,
        reason: str | None = None,
        deleted_by_user: bool = False,
    ) -> bool:
        """添加用户到黑名单"""

        # 1. 添加到黑名单表
        # ... 原有逻辑 ...

        # 2. ✅ 新增：清理该用户的补刀队列记录
        try:
            from wecom_desktop.backend.services.followup.attempts_repository import (
                FollowupAttemptsRepository
            )

            repo = FollowupAttemptsRepository()
            cancelled_count = repo.cancel_attempts_by_customer(
                device_serial=device_serial,
                customer_name=customer_name,
                reason=f"User added to blacklist: {reason or 'manual'}",
            )

            if cancelled_count > 0:
                logger.info(
                    f"Cancelled {cancelled_count} pending followup attempts for {customer_name}"
                )
        except Exception as e:
            # 清理失败不影响加入黑名单
            logger.warning(f"Failed to cancel followup attempts: {e}")

        return True
```

需要在 `FollowupAttemptsRepository` 中添加方法：

```python
def cancel_attempts_by_customer(
    self,
    device_serial: str,
    customer_name: str,
    reason: str | None = None,
) -> int:
    """取消指定用户的所有待补刀记录"""
    with self._get_connection() as conn:
        cursor = conn.execute(
            """UPDATE followup_attempts
               SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE device_serial = ?
                 AND customer_name = ?
                 AND status = ?""",
            (AttemptStatus.CANCELLED.value, device_serial, customer_name, AttemptStatus.PENDING.value),
        )
        conn.commit()
        return cursor.rowcount
```

### 方案 3: 混合方案（最佳实践）

结合方案 1 和方案 2:

1. **方案 2**: 用户加入黑名单时清理队列（主动）
2. **方案 1**: 执行补刀时再次检查（被动防御）

**优点**:

- ✅ 双重保险，最大程度防止误补刀
- ✅ 数据库更干净
- ✅ 兼容所有场景（包括旧数据）

## 临时缓解措施

在修复代码之前，可以通过以下方式减轻影响：

### 1. 手动清理数据库

```sql
-- 查询黑名单用户的待补刀记录
SELECT fa.id, fa.customer_name, fa.current_attempt, fa.status, b.is_blacklisted
FROM followup_attempts fa
INNER JOIN blacklist b
  ON fa.device_serial = b.device_serial
  AND fa.customer_name = b.customer_name
WHERE fa.status = 'pending'
  AND b.is_blacklisted = 1;

-- 取消这些记录
UPDATE followup_attempts
SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
WHERE id IN (
  SELECT fa.id
  FROM followup_attempts fa
  INNER JOIN blacklist b
    ON fa.device_serial = b.device_serial
    AND fa.customer_name = b.customer_name
  WHERE fa.status = 'pending'
    AND b.is_blacklisted = 1
);
```

### 2. 定期清理脚本

```python
#!/usr/bin/env python3
"""清理黑名单用户的补刀队列记录"""

from wecom_automation.core.config import get_default_db_path
from wecom_desktop.backend.services.followup.attempts_repository import (
    FollowupAttemptsRepository,
)
from wecom_desktop.backend.services.blacklist_service import BlacklistService

def cleanup_blacklisted_attempts():
    """清理黑名单用户的待补刀记录"""
    repo = FollowupAttemptsRepository()
    blacklist_service = BlacklistService()

    # 获取所有待补刀记录
    pending = repo.get_all_pending_attempts()

    cancelled_count = 0
    for attempt in pending:
        if blacklist_service.is_blacklisted(
            attempt.device_serial,
            attempt.customer_name,
            attempt.customer_id,
        ):
            repo.cancel_attempt(attempt.id, reason="User in blacklist")
            cancelled_count += 1
            print(f"✅ Cancelled: {attempt.customer_name}")

    print(f"\n🎉 Total cancelled: {cancelled_count}")

if __name__ == "__main__":
    cleanup_blacklisted_attempts()
```

## 测试计划

### 测试用例

#### 1. 基本黑名单过滤

```python
def test_execute_followups_skips_blacklisted_user():
    """测试：执行补刀时跳过黑名单用户"""

    # 1. 用户加入补刀队列
    repo.add_or_update(
        device_serial="TEST123",
        customer_name="张三",
        last_kefu_message_id="msg_001",
    )

    # 2. 用户被加入黑名单
    blacklist_service.add_to_blacklist(
        device_serial="TEST123",
        customer_name="张三",
        reason="Test",
    )

    # 3. 执行补刀
    result = await queue_manager.execute_pending_followups()

    # 4. 验证：用户被跳过
    assert result["skipped_blacklisted"] == 1
    assert result["success"] == 0
```

#### 2. 黑名单检查失败时的容错

```python
def test_execute_followups_continues_on_blacklist_check_failure():
    """测试：黑名单检查失败时继续执行（容错）"""

    # Mock 黑名单检查失败
    with patch.object(BlacklistChecker, 'is_blacklisted', side_effect=Exception("DB error")):
        result = await queue_manager.execute_pending_followups()

    # 验证：虽然检查失败，但仍然执行了补刀（容错机制）
    assert result["success"] > 0
```

#### 3. 用户加入黑名单后清理队列

```python
def test_add_to_blacklist_cancels_pending_attempts():
    """测试：用户加入黑名单时清理补刀队列"""

    # 1. 用户有待补刀记录
    repo.add_or_update(
        device_serial="TEST123",
        customer_name="李四",
        last_kefu_message_id="msg_002",
    )

    # 2. 加入黑名单
    blacklist_service.add_to_blacklist(
        device_serial="TEST123",
        customer_name="李四",
        reason="Test",
    )

    # 3. 验证：补刀记录被取消
    pending = repo.get_pending_attempts("TEST123")
    assert all(p.customer_name != "李四" for p in pending)
```

### 手动测试步骤

1. **准备环境**
   - 启动桌面应用
   - 连接测试设备
   - 创建测试用户 "测试用户A"

2. **制造场景**
   - 让 "测试用户A" 闲置 30 分钟（修改数据库模拟）
   - 等待补刀扫描，确认用户加入队列

3. **加入黑名单**
   - 在黑名单管理页面将 "测试用户A" 加入黑名单

4. **执行补刀**
   - 触发补刀执行
   - 查看日志，确认 "测试用户A" 被跳过

5. **验证结果**
   - 检查设备：测试用户A 没有收到补刀消息
   - 检查数据库：`followup_attempts` 表中该用户记录状态为 `cancelled` 或被跳过

## 相关文档

- [补刀系统黑名单过滤功能](../../01-product/followup-blacklist-integration.md) - 当前实现文档
- [黑名单系统设计](../../01-product/blacklist-system.md) - 黑名单系统整体设计
- [补刀系统逻辑文档](../../03-impl-and-arch/key-modules/followup-system-logic.md) - 补刀系统核心逻辑

## 实施计划

### Phase 1: 紧急修复（推荐方案 1）

- [ ] 在 `execute_pending_followups()` 中添加黑名单检查
- [ ] 添加 `skipped_blacklisted` 统计
- [ ] 更新日志输出
- [ ] 编写单元测试
- [ ] 手动测试验证

### Phase 2: 主动清理（推荐方案 2）

- [ ] 在 `BlacklistService.add_to_blacklist()` 中添加队列清理逻辑
- [ ] 在 `FollowupAttemptsRepository` 中添加 `cancel_attempts_by_customer()` 方法
- [ ] 编写单元测试
- [ ] 手动测试验证

### Phase 3: 历史数据清理

- [ ] 编写清理脚本
- [ ] 在生产环境执行清理
- [ ] 验证数据一致性

### Phase 4: 文档更新

- [ ] 更新 `followup-blacklist-integration.md`
- [ ] 更新 `CLAUDE.md` 补刀系统部分
- [ ] 记录修复日志

## 附录

### 相关代码位置

```
wecom-desktop/backend/services/followup/
├── queue_manager.py             # 补刀队列管理器（需修改）
├── attempts_repository.py       # 补刀记录仓库（需添加方法）
└── executor.py                  # 补刀执行器

wecom-desktop/backend/services/
└── blacklist_service.py         # 黑名单服务（需添加清理逻辑）

wecom_automation/services/
└── blacklist_service.py         # 黑名单检查器（共用）
```

### 数据库表结构

#### followup_attempts 表

```sql
CREATE TABLE IF NOT EXISTS followup_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_id TEXT,

    last_kefu_message_id TEXT NOT NULL,
    last_kefu_message_time DATETIME,
    last_checked_message_id TEXT,

    max_attempts INTEGER NOT NULL DEFAULT 3,
    current_attempt INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_followup_at DATETIME,

    UNIQUE(device_serial, customer_name)
);
```

#### blacklist 表

```sql
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_channel TEXT,
    is_blacklisted INTEGER DEFAULT 1,
    reason TEXT,
    deleted_by_user INTEGER DEFAULT 0,
    avatar_url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(device_serial, customer_name, customer_channel)
);
```

---

## 修复实施记录

### ✅ 已完成

**实施时间**: 2026-02-06

#### Phase 1: 执行补刀时添加黑名单过滤

**文件**: `wecom-desktop/backend/services/followup/queue_manager.py`

**改动**:

1. **添加黑名单跳过统计**:

```python
results = {
    "executed": True,
    "total": len(pending),
    "success": 0,
    "failed": 0,
    "skipped": 0,
    "skipped_blacklisted": 0,  # ✅ 新增
    "details": [],
}
```

2. **执行前检查黑名单**:

```python
# ✅ 新增：执行前再次检查黑名单
self._log("  🔍 检查黑名单状态...")
try:
    from wecom_automation.services.blacklist_service import BlacklistChecker

    if BlacklistChecker.is_blacklisted(
        self.device_serial,
        attempt.customer_name,
        attempt.customer_id,
        use_cache=False,  # 实时检查
    ):
        self._log("  ⛔ 黑名单用户，跳过补刀")
        results["skipped"] += 1
        results["skipped_blacklisted"] += 1

        # 标记为 cancelled
        repo.update_status(attempt.id, AttemptStatus.CANCELLED)

        results["details"].append({
            "customer": attempt.customer_name,
            "status": "skipped_blacklisted",
            "error": "User is in blacklist",
            "duration_ms": 0,
        })
        continue
except Exception as e:
    # 容错处理
    self._log(f"  ⚠️ 黑名单检查失败: {e}，继续执行补刀", "WARN")
```

3. **更新日志输出**:

```python
if results.get("skipped_blacklisted", 0) > 0:
    self._log(f"║    - 其中黑名单用户: {results['skipped_blacklisted']:<39}║")
```

#### Phase 2: 加入黑名单时清理补刀队列

**文件 1**: `wecom-desktop/backend/services/blacklist_service.py`

**改动**: 在 `add_to_blacklist()` 方法中添加清理逻辑:

```python
# ✅ 新增：清理该用户的补刀队列记录
try:
    from wecom_desktop.backend.services.followup.attempts_repository import (
        FollowupAttemptsRepository,
    )

    repo = FollowupAttemptsRepository(self._db_path)
    cancelled_count = repo.cancel_attempts_by_customer(
        device_serial=device_serial,
        customer_name=customer_name,
        reason=f"User added to blacklist: {reason or 'manual'}",
    )

    if cancelled_count > 0:
        logger.info(
            f"Cancelled {cancelled_count} pending followup attempts for {customer_name}"
        )
except Exception as e:
    # 清理失败不影响加入黑名单
    logger.warning(f"Failed to cancel followup attempts: {e}")
```

**文件 2**: `wecom-desktop/backend/services/followup/attempts_repository.py`

**改动**: 添加 `cancel_attempts_by_customer()` 方法:

```python
def cancel_attempts_by_customer(
    self,
    device_serial: str,
    customer_name: str,
    reason: str | None = None,
) -> int:
    """取消指定用户的所有待补刀记录"""
    with self._get_connection() as conn:
        now = datetime.now().isoformat()
        cursor = conn.execute(
            """UPDATE followup_attempts
               SET status = ?, updated_at = ?
               WHERE device_serial = ?
                 AND customer_name = ?
                 AND status = ?""",
            (AttemptStatus.CANCELLED.value, now, device_serial, customer_name, AttemptStatus.PENDING.value),
        )
        conn.commit()
        cancelled_count = cursor.rowcount

        if cancelled_count > 0:
            logger.info(
                f"Cancelled {cancelled_count} pending attempts for {customer_name} "
                f"on {device_serial}. Reason: {reason or 'N/A'}"
            )

        return cancelled_count
```

#### Phase 3: 历史数据清理脚本

**文件**: `scripts/cleanup_blacklisted_followup_attempts.py`

**功能**:

- 查找所有黑名单用户的待补刀记录
- 支持 dry-run 模式（仅查看，不修改）
- 批量取消这些记录

**使用方式**:

```bash
# 查看需要清理的记录
python scripts/cleanup_blacklisted_followup_attempts.py --dry-run

# 执行清理
python scripts/cleanup_blacklisted_followup_attempts.py
```

### 验证结果

#### 预期行为

1. **新的补刀流程**:
   - 用户加入补刀队列时：检查黑名单 ✅
   - 执行补刀时：再次检查黑名单 ✅（双重防护）
   - 日志显示黑名单用户被跳过 ✅

2. **加入黑名单时**:
   - 自动清理该用户的补刀队列记录 ✅
   - 日志记录清理操作 ✅

3. **历史数据**:
   - 通过清理脚本一次性清理 ✅

#### 测试要点

- [ ] 用户加入黑名单后，补刀队列中的记录被自动取消
- [ ] 执行补刀时，黑名单用户被跳过
- [ ] 日志正确显示 "⛔ 黑名单用户，跳过补刀"
- [ ] 统计信息包含黑名单跳过计数
- [ ] 清理脚本能正确找到并清理历史记录

### 下一步

1. **立即执行**: 运行清理脚本清理历史数据
2. **监控**: 观察下次补刀执行的日志
3. **验证**: 确认黑名单用户不再收到补刀消息
4. **通知用户**: 告知问题已修复，建议更新代码

---

**修复完成时间**: 2026-02-06  
**修复方案**: 双重防护（执行时检查 + 加入黑名单时清理）  
**预计影响**: 彻底解决黑名单用户被补刀的问题
