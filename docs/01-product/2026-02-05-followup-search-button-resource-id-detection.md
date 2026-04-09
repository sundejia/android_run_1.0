# 补刀搜索按钮 Resource ID 检测实现

> 文档创建：2026-02-05
> 状态：已实现

## 背景

在补刀（FollowUp）系统中，搜索按钮检测是关键的第一步。之前的实现依赖于文本匹配和坐标定位，存在以下问题：

1. **文本匹配不稳定**：搜索按钮图标在不同版本中可能没有 `text` 或 `contentDescription`
2. **坐标定位脆弱**：屏幕分辨率和UI布局变化会导致坐标失效
3. **UI 树遍历低效**：深度遍历整棵树来查找搜索元素

为了解决这些问题，我们引入了 **方法0（Method 0）**：基于 `resourceId` 在 `clickable_elements_cache` 中直接定位搜索按钮。

## 核心实现

### 1. Resource ID 常量定义

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/executor.py`

```python
class FollowupExecutor:
    # 搜索按钮 resourceId（来自 UI tree：com.tencent.wework:id/ngq）
    SEARCH_ICON_RESOURCE_ID = "com.tencent.wework:id/ngq"
```

### 2. 按 Resource ID 查找元素

新增 `_find_clickable_by_resource_id()` 方法：

```python
def _find_clickable_by_resource_id(
    self,
    elements: list[dict],
    resource_id: str,
    class_name: str | None = None,
) -> dict | None:
    """
    从 clickable_elements_cache 中按 resourceId 精确匹配元素。

    优先用于搜索按钮：这种 icon 在 UI tree 里经常没有 text/desc，
    但 clickable cache 里通常能稳定拿到 resourceId + index。
    """
    expected_cls = self._normalize_class_name(class_name or "") if class_name else ""

    for el in elements:
        rid = str(el.get("resourceId", "") or "")
        cls = str(el.get("className", "") or "")
        clickable = el.get("clickable", el.get("isClickable"))
        if clickable is not None and not bool(clickable):
            continue

        if rid != resource_id:
            continue

        if expected_cls:
            actual_cls = self._normalize_class_name(cls)
            if actual_cls != expected_cls:
                continue

        # 优先用 index 点击；如果有 index，就不强制要求 bounds
        if el.get("index") is not None:
            return el

        # 没 index 时才依赖 bounds 做坐标兜底
        bounds = el.get("bounds") or el.get("boundsInScreen") or {}
        if isinstance(bounds, str):
            try:
                l, t, r, b = [int(x.strip()) for x in bounds.split(",")]
                bounds = {"left": l, "top": t, "right": r, "bottom": b}
            except Exception:
                bounds = {}
        if not isinstance(bounds, dict) or bounds.get("right", 0) <= bounds.get("left", 0):
            continue
        return el

    # className 可能在不同版本不一致，允许只按 rid 回退一次
    if expected_cls:
        for el in elements:
            rid = str(el.get("resourceId", "") or "")
            clickable = el.get("clickable", el.get("isClickable"))
            if clickable is not None and not bool(clickable):
                continue
            if rid != resource_id:
                continue

            if el.get("index") is not None:
                return el

            bounds = el.get("bounds") or el.get("boundsInScreen") or {}
            if isinstance(bounds, str):
                try:
                    l, t, r, b = [int(x.strip()) for x in bounds.split(",")]
                    bounds = {"left": l, "top": t, "right": r, "bottom": b}
                except Exception:
                    bounds = {}
            if not isinstance(bounds, dict) or bounds.get("right", 0) <= bounds.get("left", 0):
                continue
            return el

    return None
```

### 3. ClassName 归一化

新增 `_normalize_class_name()` 方法处理不同版本的 className 格式差异：

```python
def _normalize_class_name(self, class_name: str) -> str:
    """把 className 归一化为末段（兼容 'TextView' vs 'android.widget.TextView'）。"""
    value = (class_name or "").strip()
    if "." in value:
        return value.split(".")[-1]
    return value
```

### 4. 方法0：搜索按钮检测

新增 `_find_search_button_method0()` 方法：

```python
async def _find_search_button_method0(self, refresh_ui: bool = True) -> dict | None:
    """
    方法0：通过 resourceId 在 clickable_elements_cache 中定位搜索按钮。

    这是目前最稳定的方式：搜索按钮在 UI tree 里经常没有 text/desc，
    但 clickable_elements_cache 里通常能稳定提供 resourceId + index。

    Args:
        refresh_ui: 是否先调用 get_state 刷新缓存（建议 True）

    Returns:
        匹配到的元素 dict；未找到返回 None
    """
    if refresh_ui:
        await self._refresh_ui()

    elements = self._get_clickable_elements()
    return self._find_clickable_by_resource_id(
        elements,
        self.SEARCH_ICON_RESOURCE_ID,
        # NOTE: clickable_elements_cache 的 className 在不同版本里可能是 "TextView"
        # 或 "android.widget.TextView"，这里让匹配逻辑做归一化处理。
        class_name="android.widget.TextView",
    )
```

### 5. 更新步骤1：使用方法0优先

修改 `_step1_click_search()` 方法，优先使用方法0：

```python
async def _step1_click_search(self) -> bool:
    """步骤1: 点击搜索图标"""
    self._log("")
    self._log("┌" + "─" * 48 + "┐")
    self._log("│ 步骤1: 点击搜索图标                              │")
    self._log("└" + "─" * 48 + "┘")

    # 先刷新 UI，保证 raw_tree_cache/clickable_elements_cache 是最新的
    tree = await self._refresh_ui()
    await self._get_screen_size()
    self._log(f"  屏幕尺寸: {self.screen_width}x{self.screen_height}")

    # 方法0（新增/优先）：按 resourceId 在 clickable cache 里找搜索按钮（最稳定）
    self._log(f"  方法0: 按 resourceId 查找搜索按钮: {self.SEARCH_ICON_RESOURCE_ID}")
    el = await self._find_search_button_method0(refresh_ui=False)
    if el:
        idx = el.get("index")
        bounds = el.get("bounds") or el.get("boundsInScreen") or {}
        x, y = self._get_element_center(el)
        self._log("  ✅ 找到搜索按钮(resourceId):")
        self._log(f"     - index: {idx}")
        self._log(f"     - bounds: {bounds}")
        self._log(f"     - center: ({x}, {y})")
        if idx is not None:
            await self._tap_by_index(int(idx), "搜索按钮(resourceId/index)")
        else:
            await self._tap(int(x), int(y), "搜索按钮(resourceId/bounds)")
        await asyncio.sleep(1)
        return True

    # 方法1: 尝试通过 UI 树找搜索图标
    self._log("  方法1: 尝试通过 UI 树查找搜索图标...")
    search_elements = self._find_elements_by_text(tree, ["search", "搜索", "Search"])

    if search_elements:
        element = search_elements[0]
        x, y = self._get_element_center(element)
        bounds = element.get("bounds", {})
        self._log("  ✅ 找到搜索元素:")
        self._log(f"     - 位置: ({x}, {y})")
        self._log(f"     - bounds: {bounds}")
        self._log(f"     - text: {element.get('text', '')}")
        self._log(f"     - resourceId: {element.get('resourceId', '')}")
        await self._tap(x, y, "搜索元素")
        await asyncio.sleep(1)
        return True

    # 方法2: 使用坐标点击右上角搜索图标
    self._log("  方法2: 未找到搜索元素，使用坐标点击...")
    x = int(self.screen_width * self.SEARCH_ICON_X_RATIO)
    y = int(self.screen_height * self.SEARCH_ICON_Y_RATIO)
    self._log(f"  计算坐标: ({x}, {y})")
    self._log(f"     - X比例: {self.SEARCH_ICON_X_RATIO} × {self.screen_width} = {x}")
    self._log(f"     - Y比例: {self.SEARCH_ICON_Y_RATIO} × {self.screen_height} = {y}")
    await self._tap(x, y, "右上角搜索图标区域")
    await asyncio.sleep(1)
    return True
```

## 优势分析

### 方法0 vs 方法1 vs 方法2

| 特性       | 方法0 (Resource ID) | 方法1 (文本匹配) | 方法2 (坐标定位) |
| ---------- | ------------------- | ---------------- | ---------------- |
| 稳定性     | ⭐⭐⭐⭐⭐          | ⭐⭐⭐           | ⭐⭐             |
| 性能       | ⭐⭐⭐⭐⭐          | ⭐⭐⭐           | ⭐⭐⭐⭐⭐       |
| 维护成本   | ⭐⭐⭐⭐⭐          | ⭐⭐⭐           | ⭐⭐             |
| 版本兼容性 | ⭐⭐⭐⭐            | ⭐⭐             | ⭐               |
| 屏幕适配性 | ⭐⭐⭐⭐⭐          | ⭐⭐⭐⭐⭐       | ⭐⭐             |

### 详细优势

1. **直接访问缓存**：`clickable_elements_cache` 是 DroidRun 提供的扁平化可点击元素列表，无需遍历整棵 UI 树
2. **精确匹配**：`resourceId` 是 Android 系统级的唯一标识符，比文本更可靠
3. **支持 index 点击**：优先使用 `droidrun_index` 进行点击，比坐标点击更稳定
4. **优雅降级**：className 不匹配时自动回退到只按 resourceId 匹配
5. **向后兼容**：保留方法1和方法2作为后备方案，确保在各种情况下都能工作

## 测试验证

### 测试脚本 1: Mock 点击搜索（不发送消息）

**文件**: `followup_test/mock_followup_click_search_only.py`

```python
#!/usr/bin/env python3
"""
Mock 测试：触发"补刀流程"的起步动作，但不发送消息。

需求：
 - 使用真实手机
 - 当前屏幕就在首页（消息列表）
 - 只点击搜索按钮（resourceId=com.tencent.wework:id/ngq），不输入、不点击结果、不发送消息
 - 导出点击前后 UI tree 方便确认页面变化
"""

async def main() -> int:
    executor = FollowupExecutor(serial)
    ok = await executor.connect()
    if not ok:
        return 2

    try:
        # 点击前 dump 一次 tree
        await executor.adb.get_state()
        tree_before = getattr(executor.adb, "raw_tree_cache", None)
        # 保存 before tree...

        # NOTE: 这里故意只调用 step1，不做后续输入/发送
        await executor._step1_click_search()

        # 点击后 dump 一次 tree
        await executor.adb.get_state()
        tree_after = getattr(executor.adb, "raw_tree_cache", None)
        # 保存 after tree...

        return 0
    finally:
        await executor.disconnect()
```

**用法**：

```bash
uv run followup_test/mock_followup_click_search_only.py --serial AN2FVB1706003302
```

### 测试脚本 2: 提取搜索按钮（验证检测）

**文件**: `followup_test/test_extract_search_button_method0.py`

```python
#!/usr/bin/env python3
"""
测试脚本：验证 FollowupExecutor "方法0" 是否能从 clickable_elements_cache 提取到搜索按钮。

要求：
 - 使用真实手机（--serial）
 - 不点击、不发送消息，只做提取验证
"""

async def main() -> int:
    executor = FollowupExecutor(serial)
    ok = await executor.connect()
    if not ok:
        return 2

    try:
        # 刷新一次 UI，落盘便于排查
        await executor.adb.get_state()
        tree = getattr(executor.adb, "raw_tree_cache", None)
        clickable = getattr(executor.adb, "clickable_elements_cache", []) or []

        # 保存 tree 和 clickable 便于调试...

        print(f"clickable_elements_cache: {len(clickable)}")
        print(f"target rid: {executor.SEARCH_ICON_RESOURCE_ID}")

        el = await executor._find_search_button_method0(refresh_ui=False)
        if not el:
            print("❌ NOT FOUND (method0)")
            return 4

        # 输出找到的元素信息...
        return 0
    finally:
        await executor.disconnect()
```

**用法**：

```bash
uv run followup_test/test_extract_search_button_method0.py --serial AN2FVB1706003302
```

## 日志示例

### 成功使用方法0找到搜索按钮

```
│ 步骤1: 点击搜索图标                              │
  屏幕尺寸: 1080x2400
  方法0: 按 resourceId 查找搜索按钮: com.tencent.wework:id/ngq
  ✅ 找到搜索按钮(resourceId):
     - index: 42
     - bounds: {'left': 920, 'top': 105, 'right': 1030, 'bottom': 195}
     - center: (975, 150)
点击元素 index=42 搜索按钮(resourceId/index)
```

### 方法0失败，回退到方法1

```
│ 步骤1: 点击搜索图标                              │
  屏幕尺寸: 1080x2400
  方法0: 按 resourceId 查找搜索按钮: com.tencent.wework:id/ngq
  ⚠️ 未找到搜索按钮(resourceId)
  方法1: 尝试通过 UI 树查找搜索图标...
  ✅ 找到搜索元素:
     - 位置: (975, 150)
     - bounds: {'left': 920, 'top': 105, 'right': 1030, 'bottom': 195}
     - text: 搜索
     - resourceId: com.tencent.wework:id/ngq
点击 (975, 150) 搜索元素
```

### 所有方法失败，回退到坐标

```
│ 步骤1: 点击搜索图标                              │
  屏幕尺寸: 1080x2400
  方法0: 按 resourceId 查找搜索按钮: com.tencent.wework:id/ngq
  ⚠️ 未找到搜索按钮(resourceId)
  方法1: 尝试通过 UI 树查找搜索图标...
  ⚠️ 未找到搜索元素
  方法2: 未找到搜索元素，使用坐标点击...
  计算坐标: (885, 132)
     - X比例: 0.82 × 1080 = 885
     - Y比例: 0.055 × 2400 = 132
点击 (885, 132) 右上角搜索图标区域
```

## UI Dump 输出

测试脚本会在 `followup_test/ui_dumps/` 目录下生成以下文件：

- `followup_click_search_before_{serial}_{timestamp}.json` - 点击搜索前的 UI 树
- `followup_click_search_after_{serial}_{timestamp}.json` - 点击搜索后的 UI 树
- `extract_method0_tree_{serial}_{timestamp}.json` - 方法0测试的 UI 树
- `extract_method0_clickable_{serial}_{timestamp}.json` - 方法0测试的可点击元素
- `extract_method0_hit_{serial}_{timestamp}.json` - 方法0找到的搜索按钮

这些文件可用于：

1. 调试搜索按钮检测逻辑
2. 验证 resourceId 和 className 的匹配规则
3. 分析不同设备/版本的 UI 结构差异

## 相关文件

| 文件                                                              | 描述                        |
| ----------------------------------------------------------------- | --------------------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/executor.py`     | 补刀执行器实现              |
| `followup_test/mock_followup_click_search_only.py`                | Mock 测试脚本（只点击搜索） |
| `followup_test/test_extract_search_button_method0.py`             | 方法0 验证脚本              |
| `docs/01-product/2026-02-04-followup-search-input-improvement.md` | 搜索输入框改进文档          |

## 参考文档

- [补刀搜索输入框检测实现](./2026-02-04-followup-search-input-improvement.md)
- [补刀系统流程分析](../03-impl-and-arch/followup-flow-analysis.md)
- [补刀系统改进计划](../03-impl-and-arch/followup-improvement-plan.md)
- [黑名单集成文档](./followup-blacklist-integration.md)
