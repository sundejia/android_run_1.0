# 黑名单名称优先匹配修复

**日期**: 2026-02-13
**状态**: ✅ 已修复
**模块**: `src/wecom_automation/services/blacklist_service.py`

---

## 概述

修复了黑名单系统因渠道（channel）显示不一致导致的匹配失败问题。现在黑名单检查仅基于 `customer_name`，忽略 `customer_channel` 的差异。

---

## 问题描述

### 症状

用户在 Sidecar 会话详情页被拉黑后，返回消息列表时黑名单检查失败：

```
# Sidecar 视图（会话详情页）
customer_channel = "＠微信"  # 全角 @ 符号

# 消息列表视图
customer_channel = "@微信"   # 半角 @ 符号

# 结果：同一用户被误判为不同用户
```

### 影响场景

1. **Sidecar 拉黑流程**：用户在会话详情页被拉黑，返回列表后仍被处理
2. **Follow-up 补刀**：已拉黑用户仍被加入补刀队列
3. **同步流程**：黑名单用户仍被同步

---

## 根本原因

1. **渠道显示不一致**：WeCom 不同视图显示的 channel 格式可能不同
   - 全角 vs 半角 @ 符号（`＠` vs `@`）
   - 可能有额外的空格或前缀

2. **原始匹配逻辑**：黑名单检查使用 `(customer_name, customer_channel)` 组合匹配

   ```python
   # 旧逻辑
   return (customer_name, customer_channel) in cls._cache[device_serial]
   ```

3. **业务逻辑**：在实际业务中，`customer_name` 本身就是唯一标识，channel 仅用于显示

---

## 修复内容

### 文件：`src/wecom_automation/services/blacklist_service.py`

#### 1. 新增渠道标准化函数

```python
def _normalize_channel(channel: str | None) -> str | None:
    """Normalize channel text to reduce cross-view mismatches."""
    if channel is None:
        return None
    normalized = channel.strip().replace("＠", "@")
    return normalized or None
```

#### 2. 修改 BlacklistChecker.is_blacklisted()

```python
# 旧逻辑
return (customer_name, customer_channel) in cls._cache[device_serial]

# 新逻辑 - 仅按名称匹配
entries = cls._cache[device_serial]
return any(name == customer_name for name, _channel in entries)
```

#### 3. 修改 BlacklistWriter 写入/移除逻辑

```python
# add_to_blacklist 和 remove_from_blacklist 现在仅按名称查找
cursor.execute(
    """
    SELECT id FROM blacklist
    WHERE device_serial = ?
        AND customer_name = ?
    """,
    (device_serial, customer_name),  # 不再包含 customer_channel
)
```

---

## 新增测试

**文件**: `tests/unit/test_blacklist_channel_matching.py`

```python
def test_is_blacklisted_ignores_channel_when_name_matches(tmp_path, monkeypatch):
    """测试名称匹配时忽略渠道差异"""
    writer = BlacklistWriter()
    assert writer.add_to_blacklist("D1", "Alice", "＠微信", reason="test")

    # 全角 vs 半角 @ 符号应视为同一用户
    assert BlacklistChecker.is_blacklisted("D1", "Alice", "@微信") is True
    # 完全不同的渠道也应视为同一用户
    assert BlacklistChecker.is_blacklisted("D1", "Alice", "completely-different") is True


def test_remove_from_blacklist_works_even_if_channel_differs(tmp_path, monkeypatch):
    """测试移除黑名单时渠道差异不影响"""
    writer = BlacklistWriter()
    assert writer.add_to_blacklist("D1", "Bob", None, reason="sidecar-no-channel")

    # 不同渠道移除应成功
    assert writer.remove_from_blacklist("D1", "Bob", "@WeChat") is True
    assert BlacklistChecker.is_blacklisted("D1", "Bob", "@WeChat") is False
```

---

## 测试结果

```
tests/unit/test_blacklist_channel_matching.py::test_is_blacklisted_ignores_channel_when_name_matches PASSED
tests/unit/test_blacklist_channel_matching.py::test_remove_from_blacklist_works_even_if_channel_differs PASSED

====================== 393 passed, 4 warnings in 15.06s =======================
```

---

## 影响范围

- ✅ Sidecar 和主界面黑名单行为一致
- ✅ 解决跨视图渠道不一致导致的误判
- ✅ Follow-up 不再处理已拉黑用户
- ⚠️ 同名不同渠道的用户将被视为同一用户（业务上可接受）

---

## 注意事项

1. **同名用户问题**：如果业务上存在同名不同用户的情况，可能需要额外的唯一标识（如 customer_db_id）
2. **数据迁移**：无需迁移，现有数据库记录保持不变
3. **向后兼容**：channel 字段仍然存储，仅匹配逻辑改变

---

## 相关文档

- `docs/01-product/blacklist-system.md` - 黑名单系统设计文档
- `docs/03-impl-and-arch/key-modules/blacklist-dual-implementation-analysis.md` - 实现分析
