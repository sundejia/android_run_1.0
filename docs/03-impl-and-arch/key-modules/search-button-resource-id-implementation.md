# 搜索按钮 Resource ID 匹配实现总结

## 概述

本次更新解决了主流程中点击搜索图标不稳定的问题，通过在 `clickable_elements_cache` 中按 `resourceId` 精确匹配搜索按钮，大幅提升了点击的成功率和稳定性。

**问题背景**：

- 测试脚本 `followup_test/test_search_followup.py` 中点击搜索图标可用
- 主流程 `wecom-desktop/backend/servic../03-impl-and-arch/executor.py` 中点击搜索图标经常失败
- 原因：搜索图标在 UI tree 中经常没有 text/desc，只能依赖坐标兜底，不够稳定

**解决方案**：

- 新增方法 0：基于 `resourceId` 在 `clickable_elements_cache` 中精确匹配
- 利用 `index` 直接调用 `tap_by_index()`，比坐标点击更可靠

---

## 核心变更

### 1. FollowupExecutor 新增方法和常量

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/executor.py`

#### 新增常量

```python
# 搜索按钮 resourceId（来自 UI tree：com.tencent.wework:id/ngq）
SEARCH_ICON_RESOURCE_ID = "com.tencent.wework:id/ngq"
```

#### 新增方法

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
    for el in elements:
        rid = str(el.get("resourceId", "") or "")
        cls = str(el.get("className", "") or "")
        clickable = bool(el.get("clickable", el.get("isClickable", False)))
        if not clickable:
            continue
        if rid != resource_id:
            continue
        if class_name and cls != class_name:
            continue
        # 需要 bounds 可用于坐标兜底
        bounds = el.get("bounds") or el.get("boundsInScreen") or {}
        if not isinstance(bounds, dict) or bounds.get("right", 0) <= bounds.get("left", 0):
            continue
        return el

    # className 可能在不同版本不一致，允许只按 rid 回退一次
    if class_name:
        for el in elements:
            rid = str(el.get("resourceId", "") or "")
            clickable = bool(el.get("clickable", el.get("isClickable", False)))
            if not clickable or rid != resource_id:
                continue
            bounds = el.get("bounds") or el.get("boundsInScreen") or {}
            if not isinstance(bounds, dict) or bounds.get("right", 0) <= bounds.get("left", 0):
                continue
            return el

    return None
```

#### 改进方法

**`_get_element_center()` - 兼容不同字段命名**：

```python
def _get_element_center(self, element: dict) -> tuple[int, int]:
    """获取元素中心坐标"""
    # clickable_elements_cache 通常是 bounds；部分 tree dump 可能是 boundsInScreen
    bounds = element.get("bounds") or element.get("boundsInScreen") or {}
    x = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
    y = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
    return (x, y)
```

**`_step1_click_search()` - 新增方法 0**：

```python
async def _step1_click_search(self) -> bool:
    """步骤1: 点击搜索图标"""
    self._log("┌" + "─" * 48 + "┐")
    self._log("│ 步骤1: 点击搜索图标                              │")
    self._log("└" + "─" * 48 + "┘")

    # 先刷新 UI，保证 raw_tree_cache/clickable_elements_cache 是最新的
    tree = await self._refresh_ui()
    await self._get_screen_size()
    self._log(f"  屏幕尺寸: {self.screen_width}x{self.screen_height}")

    # 方法0（新增/优先）：按 resourceId 在 clickable cache 里找搜索按钮（最稳定）
    self._log(f"  方法0: 按 resourceId 查找搜索按钮: {self.SEARCH_ICON_RESOURCE_ID}")
    elements = self._get_clickable_elements()
    el = self._find_clickable_by_resource_id(
        elements,
        self.SEARCH_ICON_RESOURCE_ID,
        class_name="android.widget.TextView",
    )
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

    # 方法1: 尝试通过 UI 树找搜索图标（原有逻辑）
    # ...
```

---

## 新增测试和工具

### 1. 独立测试脚本

**文件**: `followup_test/test_click_search_by_resource.py`

功能：

- 从 UI tree / clickable cache 精确匹配搜索按钮并点击
- 支持自定义 resourceId 和 className
- 导出 before/after UI tree 供调试

用法：

```bash
uv run followup_test/test_click_search_by_resource.py --serial AN2FVB1706003302
```

### 2. UI 树导出工具

**文件**: `followup_test/get_ui_tree.py`

功能：

- 导出当前设备的 UI tree 到 JSON 文件
- 便于离线分析和查找元素

用法：

```bash
uv run followup_test/get_ui_tree.py --serial AN2FVB1706003302 --out ui_tree_dump.json
```

---

## 技术细节

### 为什么使用 clickable_elements_cache？

1. **包含 index 字段**：可直接调用 `tap_by_index()`，比坐标点击更稳定
2. **元素完整**：包含 resourceId、className、bounds、clickable 等关键信息
3. **性能更好**：O(n) 线性查找，比递归遍历 UI tree 更快

### 为什么同时支持 bounds 和 boundsInScreen？

不同数据源的字段命名不一致：

- `clickable_elements_cache` 通常使用 `bounds`
- 部分 UI tree dump 使用 `boundsInScreen`
- 同时支持两者可以提高兼容性

### 为什么有 className 回退机制？

不同 WeCom 版本的 className 可能不同：

- 正常情况：`android.widget.TextView`
- 某些版本可能是其他类型
- 允许只按 resourceId 查找一次作为回退

---

## 测试验证

### 单元测试

所有 391 个单元测试通过：

```bash
uv run pytest tests/unit/ -v
# ======================= 391 passed, 3 warnings in 12.57s =======================
```

### 真实设备测试

使用独立测试脚本验证：

```bash
uv run followup_test/test_click_search_by_resource.py --serial AN2FVB1706003302
```

预期输出：

```
[AN2FVB1706003302] get_state (before click)...
[AN2FVB1706003302] saved: ui_before_AN2FVB1706003302_20250205_HHMMSS.json
[AN2FVB1706003302] clickable elements: 58
[AN2FVB1706003302] ✅ found in clickable cache: rid=com.tencent.wework:id/ngq, class=android.widget.TextView, index=42
[AN2FVB1706003302]    bounds={'left': 885, 'top': 98, 'right': 1036, 'bottom': 154}, center=(960,126)
[AN2FVB1706003302] tapping by index=42 ...
[AN2FVB1706003302] get_state (after click)...
[AN2FVB1706003302] saved: ui_after_AN2FVB1706003302_20250205_HHMMSS.json
[AN2FVB1706003302] ✅ done
```

---

## 相关文档

- `do../03-impl-and-arch/search-icon-click-comparison.md` - 问题分析和对比
- `followup_test/test_search_followup.py` - 原有测试脚本
- `followup_test/test_search_and_chat.py` - 可行性测试脚本

---

## 后续改进方向

1. **页面状态验证**：点击前确认当前确实在消息列表页面
2. **更多元素使用 resourceId**：将此方法应用到其他不稳定的元素定位
3. **自动发现 resourceId**：从 UI tree 中自动记录常见元素的 resourceId 模式
4. **失败恢复机制**：当所有方法都失败时，自动导航回已知页面重试

---

## 变更日志

- **2025-02-05**: 初始实现，新增方法 0（resourceId 匹配），解决主流程点击搜索图标不稳定的问题
