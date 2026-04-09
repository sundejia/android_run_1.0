# 2025-01-31: 锚点检测方案与发送按钮增强

## 概述

本次实现包含两项主要改动：

1. **锚点检测方案** - 替换原有消息去重逻辑，解决 AI 回复后消息发送者误识别问题
2. **发送按钮查找增强** - 结合测试脚本优点，增强主系统发送按钮查找逻辑

---

## 1. 锚点检测方案（MessageTracker）

### 问题背景

AI 回复后，在交互等待循环中检测新消息时，会将 Agent 之前发送的消息错误识别为客户发送的新消息。

**根本原因**：原有签名 `is_self|type|content|timestamp` 依赖 `is_self`，而 UI 解析的 `is_self` 可能因渲染时机、头像加载等产生不一致。

### 解决方案

采用**锚点检测（Anchor-based Detection）**：

- **签名设计**：`type|content[:80]`（不含 `is_self`、`timestamp`）
- **核心数据结构**：
  - `last_signatures`: 带索引签名 `type|content|idx:N`，用于追踪位置
  - `processed_signatures`: 基础签名，用于防止重复处理
- **检测逻辑**：同时满足「内容未处理过」且「位置未见过」→ 新消息

### 修改文件

| 文件                                                                   | 改动                                                                                                               |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 新增 `MessageTracker` 类，替换 `_interactive_wait_loop` 中的 `seen_signatures` 逻辑，删除 `_get_message_signature` |

### 测试验证

- `test_anchor_detection.py` - 模拟测试与真机循环测试
- 真机测试：正确检测新消息（如 "我"、"你好我是孙德家"、"ok"），旧消息未重复检测

### 相关文档

- 问题分析：`docs/04-bugs-and-fixes/fixed/2025/01-31-message-sender-misidentification.md`
- 测试脚本：`test_anchor_detection.py`

---

## 2. 发送按钮查找增强

### 改动内容

增强 `WeComService._find_send_button`，结合 `followup_test/test_search_followup.py` 的优点：

| 增强项   | 之前                         | 之后                               |
| -------- | ---------------------------- | ---------------------------------- |
| 关键词   | `send`, `发送`, `ie3`, `iew` | + `idf`                            |
| 精确匹配 | 无                           | 优先 `Button` 类 + `SEND`/`发送`   |
| 深度限制 | 无                           | 最大 30 层                         |
| 查找策略 | 单阶段                       | 三阶段（精确匹配 → 关键词 → 递归） |

### 修改文件

| 文件                                             | 改动                          |
| ------------------------------------------------ | ----------------------------- |
| `src/wecom_automation/services/wecom_service.py` | 增强 `_find_send_button` 方法 |

### 相关文档

- `docs/01-product/send-button-detection.md` - 完整发送按钮检测文档

---

## 3. 新增文档

| 文档                                                                                           | 说明                   |
| ---------------------------------------------------------------------------------------------- | ---------------------- |
| `docs/01-product/send-button-detection.md`                                                     | 发送按钮检测与点击机制 |
| `do../03-impl-and-arch/experiments/2025-01-31-anchor-detection-and-send-button-enhancement.md` | 本文档                 |

---

## 4. 辅助测试脚本

以下脚本用于验证锚点算法，位于项目根目录：

| 脚本                       | 用途                    |
| -------------------------- | ----------------------- |
| `test_anchor_detection.py` | 锚点检测模拟 + 真机测试 |
| `test_signature_scheme.py` | 签名方案模拟对比        |
| `test_real_signature.py`   | 真机签名方案测试        |
| `test_is_self_debug.py`    | is_self 检测调试        |

注：根据 `docs/development/test-organization.md`，正式单元测试应放在 `tests/unit/`，上述脚本为临时调试用。
