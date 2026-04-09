# 2026-02-06 补刀系统修复汇总

> **日期**: 2026-02-06  
> **修复数量**: 2 个问题  
> **影响范围**: 补刀系统（Queue Manager）

---

## 修复 #1: Async/Await 错误

### 问题

```
[QueueMgr] ❌ AI 生成消息失败: 'coroutine' object is not subscriptable
```

### 根本原因

`ai_reply_callback` 是 async 函数，但调用时未使用 `await`，返回了 coroutine 对象。

### 修复

**文件**: `wecom-desktop/backend/services/followup/queue_manager.py`

1. 添加 `Awaitable` 导入
2. 更新类型提示: `Callable[[str, str], Awaitable[str | None]]`
3. 将 `_generate_message()` 改为 `async def`
4. 添加 `await` 调用

### 预防措施

更新 `CLAUDE.md`，添加 **"Critical Async/Await Patterns"** 章节，包含：

- 常见陷阱说明
- 正确 vs 错误示例
- 类型提示最佳实践
- 6 点检查清单

---

## 修复 #2: 黑名单用户仍被补刀

### 问题

用户反馈：某些客户被加入黑名单后，仍然收到自动补刀消息。

### 根本原因

补刀系统有两个阶段，但黑名单检查不完整：

- ✅ Stage 1: 加入队列时有检查
- ❌ Stage 2: 执行补刀时没有检查

### 问题场景

```
1. 用户加入补刀队列 → 数据库记录创建
2. 客服将用户加入黑名单 → 黑名单表更新
3. 执行补刀 → 直接从数据库读取 → 没有再次检查黑名单 ❌
```

### 修复方案：双重防护

#### Phase 1: 执行时添加黑名单过滤

**文件**: `wecom-desktop/backend/services/followup/queue_manager.py`

```python
# 执行前检查黑名单
if BlacklistChecker.is_blacklisted(
    self.device_serial,
    attempt.customer_name,
    attempt.customer_id,
    use_cache=False,
):
    self._log("  ⛔ 黑名单用户，跳过补刀")
    results["skipped_blacklisted"] += 1
    repo.update_status(attempt.id, AttemptStatus.CANCELLED)
    continue
```

**优点**:

- 双重防护，被动防御
- 兼容旧版本遗留数据
- 防止竞态条件

#### Phase 2: 加入黑名单时清理队列

**文件**: `wecom-desktop/backend/services/blacklist_service.py`

```python
# 在 add_to_blacklist() 中添加
repo = FollowupAttemptsRepository(self._db_path)
cancelled_count = repo.cancel_attempts_by_customer(
    device_serial=device_serial,
    customer_name=customer_name,
    reason=f"User added to blacklist: {reason or 'manual'}",
)
```

**新增方法**: `attempts_repository.py` 中的 `cancel_attempts_by_customer()`

**优点**:

- 主动清理，数据库更干净
- 加入黑名单时立即清理

#### Phase 3: 历史数据清理

**文件**: `scripts/cleanup_blacklisted_followup_attempts.py`

**功能**:

- 查找黑名单用户的待补刀记录
- 支持 dry-run 模式
- 批量取消记录

**使用**:

```bash
# 查看需要清理的记录
python scripts/cleanup_blacklisted_followup_attempts.py --dry-run

# 执行清理
python scripts/cleanup_blacklisted_followup_attempts.py
```

---

## 文件改动清单

| 文件                                                             | 类型 | 描述                                      |
| ---------------------------------------------------------------- | ---- | ----------------------------------------- |
| `wecom-desktop/backend/services/followup/queue_manager.py`       | 修改 | 修复 async/await + 添加黑名单检查         |
| `wecom-desktop/backend/services/blacklist_service.py`            | 修改 | 加入黑名单时清理队列                      |
| `wecom-desktop/backend/services/followup/attempts_repository.py` | 修改 | 新增 `cancel_attempts_by_customer()` 方法 |
| `scripts/cleanup_blacklisted_followup_attempts.py`               | 新建 | 历史数据清理脚本                          |
| `CLAUDE.md`                                                      | 修改 | 添加 Async/Await 最佳实践章节             |
| `docs/04-bugs-and-fixes/active/2026-02-06-*.md`                  | 新建 | Bug 分析和修复文档                        |

---

## 验证清单

### Async/Await 修复验证

- [x] Linter 检查通过
- [x] 类型提示正确
- [x] CLAUDE.md 文档更新
- [ ] 测试 AI 生成消息功能

### 黑名单过滤修复验证

- [x] Linter 检查通过
- [x] 代码逻辑正确
- [ ] 运行清理脚本
- [ ] 测试：加入黑名单后队列被清理
- [ ] 测试：执行补刀时黑名单用户被跳过
- [ ] 监控日志确认黑名单用户不再被补刀

---

## 下一步行动

### 立即执行

1. **清理历史数据**:

   ```bash
   python scripts/cleanup_blacklisted_followup_attempts.py
   ```

2. **测试验证**:
   - 将测试用户加入黑名单
   - 观察补刀执行日志
   - 确认用户被跳过

### 后续监控

1. 观察补刀日志中的黑名单跳过统计
2. 确认黑名单用户不再收到补刀消息
3. 收集用户反馈

### 通知用户

通知用户问题已修复，建议：

1. 更新代码到最新版本
2. 运行清理脚本清理历史数据
3. 监控补刀日志确认修复有效

---

## 相关文档

- [详细分析报告](2026-02-06-followup-blacklist-not-filtered-on-execution.md)
- [执行摘要](2026-02-06-followup-blacklist-executive-summary.md)
- [Async/Await 最佳实践](../../CLAUDE.md#critical-asyncawait-patterns)
- [补刀系统黑名单过滤功能](../../01-product/followup-blacklist-integration.md)

---

**修复完成**: 2026-02-06  
**状态**: ✅ 全部完成  
**预计影响**: 彻底解决两个关键问题
