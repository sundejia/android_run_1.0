# 发送按钮检测与点击机制

本文档详细说明系统中如何查找并点击企业微信（WeCom）的发送按钮。

## 概述

系统提供两种发送按钮查找实现：

| 实现         | 位置                      | 使用场景               |
| ------------ | ------------------------- | ---------------------- |
| **主系统**   | `wecom_service.py`        | 日常消息发送、同步流程 |
| **测试脚本** | `test_search_followup.py` | 补刀功能测试、调试     |

两种实现都基于相同的核心思想，但有细微差异。

---

## 1. 主系统实现 (`WeComService._find_send_button`)

### 文件位置

```
src/wecom_automation/services/wecom_service.py
```

### 核心逻辑（增强版）

```python
def _find_send_button(
    self,
    elements: list[dict],
    is_flat_list: bool = False,
    _depth: int = 0,
) -> dict | None:
    """
    Find the send button in the UI.

    Enhanced strategy:
    1. Precise match first: Button class + SEND/发送 text (highest priority)
    2. Keyword match: check text, resourceId, contentDescription
    3. Recursive search with depth limit (max 30 levels)

    Args:
        elements: List of UI elements to search
        is_flat_list: If True, skip recursive child search (optimized for
                     flat lists like clickable_elements_cache)
        _depth: Internal recursion depth counter (max 30)
    """
    # Depth limit to prevent infinite recursion
    if _depth > 30:
        return None

    # Extended hints: ie3/iew/idf are common WeCom resource IDs
    send_hints = ("send", "发送", "ie3", "iew", "idf")

    iterable = elements
    if isinstance(elements, dict):
        iterable = [elements]

    # Phase 1: Precise match - Button class with SEND/发送 text (highest priority)
    for element in iterable:
        class_name = (element.get("class") or element.get("className") or "").lower()
        text = (element.get("text") or "").lower()
        rid = (element.get("resourceId") or "").lower()

        # Precise match: Button + (SEND text or idf resourceId)
        if "button" in class_name:
            if "send" in text or "发送" in text or "idf" in rid:
                return element

    # Phase 2: Keyword match - check all hints in text/rid/contentDescription
    for element in iterable:
        text = (element.get("text") or "").lower()
        rid = (element.get("resourceId") or "").lower()
        content_desc = (element.get("contentDescription") or "").lower()

        for hint in send_hints:
            if hint in text or hint in rid or hint in content_desc:
                return element

        # Phase 3: Recursive search (only if not flat list)
        if not is_flat_list:
            children = element.get("children", [])
            if children:
                result = self._find_send_button(
                    children, is_flat_list=False, _depth=_depth + 1
                )
                if result:
                    return result

    return None
```

### 查找策略（三阶段）

| 阶段        | 策略       | 说明                                           |
| ----------- | ---------- | ---------------------------------------------- |
| **Phase 1** | 精确匹配   | `Button` 类 + `SEND`/`发送` 文本（最高优先级） |
| **Phase 2** | 关键词匹配 | 检查 text/resourceId/contentDescription        |
| **Phase 3** | 递归搜索   | 搜索子节点（深度限制 30 层）                   |

### 关键词列表

| 关键词 | 含义                      |
| ------ | ------------------------- |
| `send` | 英文发送                  |
| `发送` | 中文发送                  |
| `ie3`  | WeCom 特定资源 ID         |
| `iew`  | WeCom 特定资源 ID         |
| `idf`  | WeCom 特定资源 ID（新增） |

### 搜索模式

- `is_flat_list=True`: 只搜索当前列表（用于 `clickable_elements_cache`）
- `is_flat_list=False`: 递归搜索子节点（用于完整 UI 树，深度限制 30 层）

### 完整发送流程

```python
async def send_message(self, text: str) -> tuple[bool, str]:
    """发送消息的完整流程"""

    # 1. 获取 UI 状态
    ui_tree, elements = await self.adb.get_ui_state(force=True)

    # 2. 查找并点击输入框
    input_field = self._find_input_field(elements, is_flat_list=True)
    if input_field:
        await self.adb.tap(input_field.get("index"))

    # 3. 清空输入框（防止残留文本）
    await self._clear_input_field()

    # 4. 输入消息
    await self.adb.input_text(text)

    # 5. 刷新 UI（输入后可能变化）
    ui_tree, elements = await self.adb.get_ui_state(force=True)

    # 6. 查找发送按钮（优先使用可点击元素列表）
    send_button = self._find_send_button(elements, is_flat_list=True)

    if send_button:
        await self._tap_element(send_button)
        return True, text

    # 7. 回退：在完整 UI 树中查找
    if ui_tree:
        tree_send_button = self._find_send_button(ui_tree)
        if tree_send_button:
            await self._tap_element(tree_send_button)
            return True, text

    # 8. 最终回退：按回车键发送
    await self.adb.press_enter()
    return True, text
```

### 点击方式

```python
async def _tap_element(self, element: dict, fallback_coords: tuple | None = None) -> bool:
    """点击元素，支持多种方式"""

    # 方式1: 通过 droidrun index 点击（最可靠）
    index = element.get("index")
    if index is not None:
        await self.adb.tap(index)
        return True

    # 方式2: 通过 bounds 计算中心点击
    bounds = element.get("bounds", {})
    if bounds:
        x = (bounds["left"] + bounds["right"]) // 2
        y = (bounds["top"] + bounds["bottom"]) // 2
        await self.adb.tap_by_coordinates(x, y)
        return True

    # 方式3: 使用回退坐标
    if fallback_coords:
        await self.adb.tap_by_coordinates(*fallback_coords)
        return True

    return False
```

---

## 2. 测试脚本实现 (`SearchFollowupTest`)

### 文件位置

```
followup_test/test_search_followup.py
```

### 核心逻辑

测试脚本提供两个查找方法：

#### 方法 1: 在 UI 树中查找

```python
def find_send_button(self, tree: Dict) -> Optional[Dict]:
    """查找发送按钮（在 UI 树中递归搜索）"""
    send_hints = ("send", "发送", "ie3", "iew")

    def traverse(node: Dict, depth: int = 0) -> Optional[Dict]:
        if depth > 30:
            return None

        text = str(node.get("text", "")).lower()
        rid = str(node.get("resourceId", "")).lower()
        content_desc = str(node.get("contentDescription", "")).lower()

        for hint in send_hints:
            if hint in text or hint in rid or hint in content_desc:
                return node

        for child in node.get("children", []):
            result = traverse(child, depth + 1)
            if result:
                return result
        return None

    return traverse(tree)
```

#### 方法 2: 在可点击元素中查找

```python
def find_send_in_clickable(self, elements: List[Dict]) -> Optional[Dict]:
    """在可点击元素中查找发送按钮"""

    # 优先查找：Button 类型 + SEND text 或 idf resourceId
    for element in elements:
        cls = str(element.get("className", "")).lower()
        text = str(element.get("text", "")).lower()
        rid = str(element.get("resourceId", "")).lower()

        # 精确匹配：Button + SEND text 或 idf resourceId
        if "button" in cls and ("send" in text or "idf" in rid):
            return element

    # 回退：查找包含发送关键词的元素
    send_hints = ("send", "发送", "idf")
    for element in elements:
        text = str(element.get("text", "")).lower()
        rid = str(element.get("resourceId", "")).lower()
        content_desc = str(element.get("contentDescription", "")).lower()

        for hint in send_hints:
            if hint in text or hint in rid or hint in content_desc:
                return element
    return None
```

### 完整发送流程

```python
async def step4_send_message(self, message: str) -> bool:
    """步骤4: 发送消息"""

    # 1. 刷新 UI 并获取可点击元素
    await self.refresh_ui()
    elements = self.get_clickable_elements()

    # 2. 查找并点击输入框
    input_field = self.find_input_in_clickable(elements)
    if input_field:
        index = input_field.get("index")
        if index is not None:
            await self.tap_by_index(index, "点击输入框")
        else:
            x, y = self.get_element_center(input_field)
            await self.tap(x, y, "点击输入框(bounds)")
    else:
        # 回退：坐标点击底部输入框区域
        y = int(self.screen_height * 0.965)
        x = int(self.screen_width * 0.30)
        await self.tap(x, y, "点击底部输入框区域")

    # 3. 输入消息
    await self.input_text(message)

    # 4. 刷新 UI 查找发送按钮
    await self.refresh_ui()
    elements = self.get_clickable_elements()

    send_button = self.find_send_in_clickable(elements)

    if send_button:
        index = send_button.get("index")
        if index is not None:
            await self.tap_by_index(index, "点击发送按钮")
        else:
            x, y = self.get_element_center(send_button)
            await self.tap(x, y, "点击发送按钮(bounds)")
    else:
        # 回退：按回车键发送
        await self.press_enter()

    return True
```

---

## 3. 关键词对照表

| 关键词 | 含义                                      | 匹配字段                             |
| ------ | ----------------------------------------- | ------------------------------------ |
| `send` | 英文发送                                  | text, resourceId, contentDescription |
| `发送` | 中文发送                                  | text, resourceId, contentDescription |
| `ie3`  | WeCom 发送按钮资源 ID                     | resourceId                           |
| `iew`  | WeCom 发送按钮资源 ID                     | resourceId                           |
| `idf`  | WeCom 发送按钮资源 ID（测试脚本额外支持） | resourceId                           |

---

## 4. 点击优先级

两种实现都遵循相同的点击优先级：

```
1. tap_by_index (droidrun overlay index)  ← 最可靠
   ↓ 失败
2. tap_by_coordinates (bounds 中心点)     ← 次选
   ↓ 失败
3. press_enter (回车键)                   ← 最终回退
```

### 为什么 `tap_by_index` 最可靠？

- droidrun overlay 会给每个可点击元素分配一个唯一的 `index`
- 通过 `index` 点击不受屏幕坐标偏移影响
- 无需计算元素边界

### 为什么需要 `press_enter` 回退？

- 某些情况下发送按钮可能不可见或不可点击
- 企业微信支持回车键发送消息
- 提供最后的保障机制

---

## 5. 差异对比（增强后）

| 特性       | 主系统 (`wecom_service.py`)            | 测试脚本 (`test_search_followup.py`) |
| ---------- | -------------------------------------- | ------------------------------------ |
| 关键词     | `send`, `发送`, `ie3`, `iew`, `idf` ✅ | `send`, `发送`, `ie3`, `iew`, `idf`  |
| UI 缓存    | 使用 `adb.get_ui_state()`              | 使用 `adb.get_state()`               |
| 精确匹配   | 优先 `Button` + `SEND` 组合 ✅         | 优先 `Button` + `SEND` 组合          |
| 深度限制   | 30 层 ✅                               | 30 层                                |
| 清空输入框 | 是（`_clear_input_field`）             | 否                                   |
| 坐标回退   | `send_button_coordinates` 配置         | 无                                   |

> ✅ 表示增强后新增的特性

---

## 6. 调试技巧

### 打印可点击元素

```python
elements = self.get_clickable_elements()
for i, el in enumerate(elements):
    cls = el.get("className", "")
    txt = el.get("text", "")[:20] if el.get("text") else ""
    rid = el.get("resourceId", "")[-30:] if el.get("resourceId") else ""
    idx = el.get("index", "?")
    print(f"  [{i}] index={idx}, text='{txt}', rid='{rid}'")
```

### 检测聊天页面

```python
def _is_chat_screen(self, tree, elements) -> bool:
    """检测是否在聊天页面"""
    has_back_button = False
    has_input_field = False
    has_send_button = False
    has_message_list = False

    for element in elements:
        text = (element.get("text") or "").lower()
        rid = (element.get("resourceId") or "").lower()

        # 检查发送按钮
        if any(kw in text for kw in ["发送", "send"]) or "send" in rid:
            has_send_button = True

        # ... 其他检查

    return has_back_button and (has_input_field or has_send_button)
```

---

## 7. 常见问题

### Q: 发送按钮找不到怎么办？

1. 检查是否在聊天页面
2. 确认输入框已聚焦（有文字时发送按钮才显示）
3. 使用 `debug_ui_tree.py` 查看实际 UI 结构
4. 尝试按回车键作为回退方案

### Q: 点击发送按钮无反应？

1. 检查 `index` 是否正确
2. 检查 `bounds` 坐标是否在屏幕内
3. 增加点击后的等待时间
4. 检查输入框是否为空（空消息无法发送）

### Q: 如何支持新版本 WeCom？

在关键词列表中添加新版本的资源 ID：

```python
send_hints = ("send", "发送", "ie3", "iew", "新的资源ID")
```
