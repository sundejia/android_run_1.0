# Bug: Send 按钮未被点击

## 问题描述

- **现象**: 在某台手机上输入消息后，系统没有自动点击 Send 按钮
- **对比**: 另一台手机可以正常发送
- **截图**: 显示输入框中有文字，右下角有蓝色 "SEND" 按钮

## 代码流程分析

发送消息的逻辑位于 `wecom_service.py` 的 `send_message()` 方法（第 2072-2150 行）：

```python
async def send_message(self, text: str) -> Tuple[bool, str]:
    # 1. 获取 UI 状态
    ui_tree, elements = await self.adb.get_ui_state()

    # 2. 找到输入框并点击
    input_field = self._find_input_field(elements, is_flat_list=True)
    if input_field:
        await self.adb.tap(input_index)

    # 3. 清空输入框
    await self._clear_input_field()

    # 4. 输入文本
    await self.adb.input_text(text)

    # 5. 刷新 UI 状态
    ui_tree, elements = await self.adb.get_ui_state(force=True)

    # 6. 查找 Send 按钮（关键点！）
    send_button = self._find_send_button(elements, is_flat_list=True)

    if send_button:
        # 方法1: 点击 Send 按钮
        await self._tap_element(send_button)
        return True, text

    # 方法2: 尝试从 UI 树查找
    if ui_tree:
        tree_send_button = self._find_send_button(ui_tree)
        if tree_send_button:
            await self._tap_element(tree_send_button)
            return True, text

    # 方法3: 回退使用 Enter 键发送
    await self.adb.press_enter()  # KEYCODE_ENTER = 66
    return True, text
```

## Send 按钮识别逻辑

`_find_send_button()` 方法（第 2224-2258 行）使用以下关键词识别：

```python
send_hints = ("send", "发送", "ie3", "iew")  # ie3/iew 是 WeCom 常用 resource ID

# 匹配逻辑
text = (element.get("text") or "").lower()
rid = (element.get("resourceId") or "").lower()
content_desc = (element.get("contentDescription") or "").lower()

for hint in send_hints:
    if hint in text or hint in rid or hint in content_desc:
        return element
```

## 可能的原因

### 1. Send 按钮不在 clickable elements 列表中

- DroidRun 的 `get_state()` 可能没有将 Send 按钮标记为 clickable
- 某些设备上按钮的 `clickable` 属性可能为 false

### 2. UI 元素属性差异

- 不同设备/WeCom 版本的按钮属性可能不同
- `text` 属性可能为空，`contentDescription` 可能不包含 "send" 或 "发送"
- `resourceId` 可能不包含预期的 "ie3" 或 "iew"

### 3. Enter 键行为差异

- 某些输入法/设备上，Enter 键是换行而不是发送
- WeCom 设置可能禁用了 Enter 键发送功能

### 4. 时序问题

- 输入文本后 UI 刷新不及时
- 按钮状态（enabled/disabled）可能有延迟

## 调试建议

### 1. 查看设备日志

检查是否有 "Send button not found, pressing Enter key" 的日志，确认是否走了回退逻辑。

### 2. 导出 UI 元素信息

在问题设备上运行以下调试代码：

```python
# 在 send_message 函数中添加调试日志
for i, el in enumerate(elements):
    text = el.get("text", "")
    rid = el.get("resourceId", "")
    desc = el.get("contentDescription", "")
    cls = el.get("className", "")
    if text or "send" in rid.lower() or "send" in desc.lower():
        self.logger.info(f"[DEBUG] Element {i}: text='{text}', rid='{rid}', desc='{desc}', class='{cls}'")
```

### 3. 比较两台设备的 UI 树

- 正常设备：导出成功时的 UI 元素
- 问题设备：导出失败时的 UI 元素
- 对比 Send 按钮的属性差异

## 建议修复方案

### 方案1: 增加更多识别关键词

```python
send_hints = ("send", "发送", "ie3", "iew", "发", "btn_send", "chat_send")
```

### 方案2: 使用坐标点击作为备选

```python
# 如果 Enter 键失败，尝试点击屏幕右下角区域
# 根据截图，Send 按钮在右下角
SEND_BUTTON_FALLBACK_COORDS = (950, 650)  # 需要根据屏幕分辨率调整
```

### 方案3: 增加 UI 刷新等待时间

```python
# 输入文本后等待更长时间
await self.adb.wait(1.0)  # 从 0.3s 增加到 1.0s
ui_tree, elements = await self.adb.get_ui_state(force=True)
```

### 方案4: 基于 className 识别

```python
# 额外检查 Button 类型的元素
if "button" in class_name.lower():
    # 检查位置是否在屏幕右下角
    bounds = element.get("bounds", {})
    if bounds.get("right", 0) > screen_width * 0.8:
        return element
```

## 下一步行动

1. 在问题设备上重现问题，收集详细日志
2. 导出两台设备的 UI 树进行对比
3. 确定 Send 按钮的实际属性
4. 根据发现的属性添加识别规则
