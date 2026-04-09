# 补刀功能扩展文档

> 文档创建：2026-02-05
> 状态：已实现

## 概述

本文档记录了对补刀系统的额外扩展和改进，这些改进在主会话之后完成。

## 功能扩展

### 1. 搜索查询规范化 - 支持方括号

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/executor.py`

**扩展内容**：

- 在原有半角/全角圆括号支持基础上，新增方括号支持
- 支持的分隔符：`-(`, `-（`, `-[`, `-【`
- 正则表达式更新：支持 `[\(（\[【]` 匹配

**示例**：

```
原始格式                    → 规范化结果
B2601300118-(保底正常)      → B2601300118
B2601300118-（保底正常）    → B2601300118
B2601300118-[正常]         → B2601300118
B2601300118-【正常】       → B2601300118
```

**代码变更**：

```python
# 支持半角/全角括号和方括号
for sep in ("-(", "-（", "-[", "-【"):
    if sep in raw:
        base = raw.split(sep, 1)[0].strip()
        return base or raw

# 兜底正则支持多种括号
m = re.match(r"^(B\d+)-\s*[\(（\[【].*$", raw)
```

---

### 2. AI 回复长度限制移除

**文件**: `src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py`

**变更内容**：

- 移除 50 字长度限制
- 删除 XML prompts 中的 `<length_limit>` 标签
- 更新日志输出，移除 `length_limit=50字`

**影响的场景**：

1. **补刀场景** (followup)
   - 原约束：`<length_limit>消息控制在 50 字以内</length_limit>`
   - 新约束：无长度限制

2. **回复场景** (reply)
   - 原约束：`<length_limit>回复控制在 50 字以内</length_limit>`
   - 新约束：无长度限制

**日志变更**：

```python
# 原日志
<constraints> length_limit=50字, special_commands=转人工检测

# 新日志
<constraints> special_commands=转人工检测
```

**影响**：

- AI 可以生成更长的回复
- 提供更详细和个性化的响应
- 仍需遵守其他约束（如禁止负面开场、禁止重复内容等）

---

### 3. 最近会话查询设备过滤

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

**改进内容**：

- 在查询最近会话时添加设备过滤
- 通过 `devices → kefu_devices → kefus → customers` 链接过滤
- 确保只返回特定设备的客户会话

**SQL 查询变更**：

```sql
SELECT
    c.id as customer_id,
    c.name as customer_name,
    c.channel as customer_channel,
    m.content as message_content,
    m.id as message_id,
    m.timestamp_parsed as message_time
FROM customers c
JOIN messages m ON m.customer_id = c.id
JOIN kefus k ON c.kefu_id = k.id
JOIN kefu_devices kd ON k.id = kd.kefu_id
JOIN devices d ON kd.device_id = d.id
WHERE m.id = (
    SELECT MAX(m2.id) FROM messages m2
    WHERE m2.customer_id = c.id
)
AND m.timestamp_parsed >= ?
AND d.serial = ?  -- 新增：设备序列号过滤
ORDER BY m.timestamp_parsed DESC
LIMIT 50
```

**日志改进**：

```
- 时间范围: 最近 24 小时
- 截止时间: 2026-02-05T12:00:00
+ 设备过滤: AN2FVB1706003302
+ 通过 devices → kefu_devices → kefus → customers 链接按设备过滤
```

**优势**：

- 精确过滤设备特定的客户会话
- 避免跨设备的会话混淆
- 提高查询准确性和性能

---

## 其他文件变更

### 配置文件更新

**文件**:

- `wecom-desktop/backend/routers/settings.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py`
- `wecom-desktop/src/stores/settings.ts`
- `wecom-desktop/src/views/SettingsView.vue`
- `test_ai_server.py`

这些文件包含与 AI 配置和设置相关的更新，与上述功能扩展配套。

---

## 测试验证

所有变更均需通过：

1. ✅ 单元测试 (391 tests)
2. ✅ TypeScript 类型检查
3. ✅ Pre-commit hook (linting, secrets scanning)
4. ✅ Pre-push hook (type check, unit tests)

---

## 相关文档

- [补刀搜索查询规范化](../01-product/2026-02-05-followup-search-query-normalization.md)
- [补刀系统流程分析](../03-impl-and-arch/followup-flow-analysis.md)
- [AI 回复集成](../01-product/2025-12-08-ai-reply-integration.md)

---

## 版本历史

- **2026-02-05**: 初始版本，记录方括号支持、长度限制移除、设备过滤改进
