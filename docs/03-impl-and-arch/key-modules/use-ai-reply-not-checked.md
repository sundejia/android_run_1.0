# Realtime Reply 未检测「Use AI Reply」设置

## 结论

**Realtime Reply（实时回复）当前不对「Use AI Reply」（是否使用 AI 回复）进行检测。**
只要实时回复流程在跑，**所有被检测到的客户消息都会走 AI 生成并发送回复**，与前端/设置里的「Use AI Reply」开关无关。

## 依据

### 1. 设置层：存在「Use AI Reply」

- **配置键**：`use_ai_reply`（AI Reply 分类）
- **默认值**：`False`（`wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py`）
- **读取接口**：`SettingsService.is_ai_reply_enabled()`（`wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py`）

```python
# service.py
def is_ai_reply_enabled(self) -> bool:
    """检查是否启用 AI 回复"""
    return self.get(SettingCategory.AI_REPLY.value, "use_ai_reply", False)
```

也就是说，系统里是有「是否使用 AI 回复」这一开关的，且默认关。

### 2. Realtime Reply 流程：未使用该设置

实时回复的核心逻辑在 **ResponseDetector**（`wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`）中：

- **进入对话后首次回复**（`_process_unread_user_with_wait`）
  - 有「最后一条客户消息」时，直接调用 `_generate_reply()`，再 `_send_reply_wrapper()` 发送。
  - **没有任何地方调用 `is_ai_reply_enabled()` 或读取 `use_ai_reply`。**

- **交互等待循环中的新消息**（`_interactive_wait_loop`）
  - 发现新客户消息后，同样直接 `_generate_reply()` + `_send_reply_wrapper()`。
  - **同样没有对「Use AI Reply」做判断。**

因此，只要实时回复在运行，就会对所有相关客户消息发 AI 回复，与「Use AI Reply」当前是开还是关无关。

### 3. 代码位置摘要

| 场景               | 文件:方法                                                 | 行为                                                                          |
| ------------------ | --------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 进入对话后首条回复 | `response_detector.py` → `_process_unread_user_with_wait` | 有 `last_customer_msg` 即调 `_generate_reply()`，无 `use_ai_reply` 判断       |
| 等待期间新消息     | `response_detector.py` → `_interactive_wait_loop`         | 发现 `new_customer_messages` 即调 `_generate_reply()`，无 `use_ai_reply` 判断 |

ResponseDetector 的 `__init__` 只依赖 `FollowUpRepository` 和 `SettingsManager`，没有注入或使用 `SettingsService`，也没有在任何分支里根据「Use AI Reply」决定是否生成/发送回复。

## 影响

- 用户在设置中关闭「Use AI Reply」后，**仅对依赖该设置的其它逻辑生效**（若有）；
- **对 Realtime Reply 无效**：只要设备上的实时回复在跑，该设备上的会话仍会对所有检测到的消息发 AI 回复。
- 若产品预期是「关闭 Use AI Reply 后，实时回复也不发 AI」，则需要在 ResponseDetector 中增加对 `is_ai_reply_enabled()` 的检测，并在为 False 时跳过生成与发送 AI 回复。

## 建议（若需与设置一致）

若希望 Realtime Reply 尊重「Use AI Reply」：

1. 在 `ResponseDetector` 中获取 `SettingsService`（或能读取 `use_ai_reply` 的同一来源）。
2. 在以下两处调用生成/发送前增加判断：
   - `_process_unread_user_with_wait`：在调用 `_generate_reply()` 前，若 `not is_ai_reply_enabled()` 则只存消息、不生成不发送回复。
   - `_interactive_wait_loop`：在发现新客户消息后、调用 `_generate_reply()` 前，若 `not is_ai_reply_enabled()` 则只存消息、不生成不发送回复。
3. 文档与前端提示中说明：「Use AI Reply」关闭后，实时回复将只同步/存储消息，不再自动发 AI 回复。

---

_文档基于对 `response_detector.py` 与 `settings/service.py`、`defaults.py` 的代码分析。_
