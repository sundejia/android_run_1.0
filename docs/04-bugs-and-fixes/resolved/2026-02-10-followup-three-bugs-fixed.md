# Followup 系统三个 Bug 修复总结

**日期**: 2026-02-10
**状态**: ✅ 已修复
**设备**: AN2FVB1706003302
**模块**: `wecom-desktop/backend/services/followup/`

---

## 概述

这次修复了 Followup 系统中的三个关键 Bug，它们形成了一个完整的失败链：

1. **Bug 1**: 消息提取返回 0 条（WeCom 新版本 resource ID 不匹配）
2. **Bug 2**: FollowupQueueManager 缺少 `_wecom` 属性
3. **Bug 3**: 补刀搜索点击了搜索框而非搜索结果

---

## Bug 1: 消息提取返回 0 条（已修复）

### 症状

Followup 流程成功点击用户进入会话页面后，消息提取返回 0 条：

```
17:30:42 [FOLLOWUP] Extracted 0 messages from conversation
17:30:42 [WARNING]  No messages extracted, going back
```

### 根本原因

WeCom 新版本更换了 UI 元素的 resource ID：

| 用途       | 旧版 ID      | 新版 ID   | 匹配？ |
| ---------- | ------------ | --------- | ------ |
| 消息文本   | `idk`, `icx` | **`ig6`** | ❌     |
| 时间戳     | `ief`        | **`ih1`** | ❌     |
| 消息行容器 | `cmn`, `cmj` | **`coy`** | ❌     |
| 语音时长   | `ies`, `ie5` | **`ihf`** | ❌     |
| 语音转文字 | `p05`, `oyl` | **`p47`** | ❌     |
| 表情包     | `igf`        | **`ijr`** | ❌     |
| 头像       | `im4`, `ilg` | **`iov`** | ❌     |

### 修复内容

**文件 1**: `src/wecom_automation/core/config.py`

- `snippet_resource_id_hints` 新增 `ig6`
- `message_row_id_hints` 新增 `coy`
- `avatar_resource_id_hints` 新增 `iov`

**文件 2**: `src/wecom_automation/services/ui_parser.py`

- 时间戳检测：支持 `ih1`
- 语音时长检测：支持 `ihf`
- 语音转文字检测：支持 `p47`
- 表情包检测：支持 `ijr`
- 头像跳过：支持 `iov`
- 图片消息默认内容：添加 `[图片]` 占位符

### 验证结果

修复后：

```
修复前: UIParserService 提取结果: 0 条消息
修复后: UIParserService 提取结果: 5 条消息
```

---

## Bug 2: FollowupQueueManager 缺少 `_wecom` 属性（已修复）

### 症状

```
'FollowupQueueManager' object has no attribute '_wecom'
```

### 根本原因

`FollowupQueueManager.__init__()` 中没有初始化 `self._wecom`，但 `execute_pending_followups()` 方法直接使用了它。

### 修复内容

**文件**: `wecom-desktop/backend/services/followup/queue_manager.py`

1. 在 `__init__` 中添加 `self._wecom = None`
2. 新增 `_get_wecom()` 延迟初始化方法
3. 将所有 `self._wecom` 替换为 `self._get_wecom()`

---

## Bug 3: 补刀搜索点击了搜索框（已修复）

### 症状

```
17:52:26 [FOLLOWUP] ✅ 选择最佳候选:
17:52:26 [FOLLOWUP]    - center: (552, 180)    ← 搜索框位置！
```

### 根本原因

搜索输入框中回显的文本精确匹配关键词，导致打分远高于实际搜索结果。

### 修复内容

**文件**: `wecom-desktop/backend/services/followup/executor.py`

1. 新增 `_is_in_search_input_area()` 方法 — 识别搜索输入框元素
2. `_collect_search_result_candidates()` 中完全排除搜索输入框
3. 修复 `_get_screen_size()` 读取 bounds 的 key（优先 `boundsInScreen`）

---

## 影响范围

- 修复后，使用新版 WeCom 的设备都能正常提取消息
- 补刀系统现在能正确点击搜索结果
- 屏幕验证功能恢复正常

---

## 相关文件

| 文件                                                           | 修改内容              |
| -------------------------------------------------------------- | --------------------- |
| `src/wecom_automation/core/config.py`                          | 新版 resource ID 支持 |
| `src/wecom_automation/services/ui_parser.py`                   | 多处新版 ID 匹配逻辑  |
| `wecom-desktop/backend/services/followup/queue_manager.py`     | `_wecom` 属性修复     |
| `wecom-desktop/backend/services/followup/executor.py`          | 搜索框排除逻辑        |
| `wecom-desktop/backend/services/followup/response_detector.py` | 图片发送关键词新增    |

---

## 相关文档

- `docs/04-bugs-and-fixes/active/2026-02-10-followup-two-bugs-analysis.md` - 详细分析
- `docs/03-impl-and-arch/key-modules/followup-coverage-analysis.md` - 覆盖率分析
