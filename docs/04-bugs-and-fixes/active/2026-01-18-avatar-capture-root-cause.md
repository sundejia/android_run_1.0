# 头像无法获取 - 根本原因分析

**创建日期**: 2026-01-18
**文档类型**: Bug 根因分析
**更新**: 2026-01-18 14:10 - 更正 get_ui_tree 分析
**更新**: 2026-01-18 - ✅ **已修复** - 添加了 screenshot_element 方法

## 问题描述

系统无法获取用户头像，三次尝试均失败。

---

## 更正：get_ui_tree 方法确实存在

经过仔细检查，`ADBService` **确实有** `get_ui_tree` 方法：

**位置**: `adb_service.py` 第 556-583 行

```python
async def get_ui_tree(self, refresh: bool = True) -> Optional[Any]:
    """
    Get the current UI accessibility tree.
    ...
    """
    self.logger.debug("Fetching UI tree...")
    try:
        if not refresh and self._cache.is_valid():
            return self._cache.raw_tree

        await self._refresh_ui_state()
        return self._cache.raw_tree
    except Exception as e:
        self.logger.error(f"Failed to get UI tree: {e}")
        return None
```

所以 `AvatarManager` 的代码检查应该能找到这个方法：

```python
elif hasattr(self._wecom, 'adb') and hasattr(self._wecom.adb, 'get_ui_tree'):
    # ✅ 这个分支应该会被执行
    tree = await self._wecom.adb.get_ui_tree()
```

---

## 真正的根本原因

### 原因 1: 缺少 `screenshot_element` 方法

`AvatarManager` 中的代码（第 251-263 行）：

```python
if hasattr(self._wecom, 'screenshot_element'):
    bounds_str = f"[{avatar_bounds[0]},{avatar_bounds[1]}][{avatar_bounds[2]},{avatar_bounds[3]}]"
    await self._wecom.screenshot_element(bounds_str, str(filepath))
else:
    await self._log("ERROR", f"screenshot_element method not found on wecom_service")
```

**问题**: `WeComService` **没有** `screenshot_element` 方法！

搜索确认：`WeComService` 没有定义 `screenshot_element` 方法。

**结果**: 即使能找到头像位置，代码也会进入 `else` 分支，记录错误并返回 `None`。

---

### 原因 2: 捕获时机问题（次要）

`CustomerSyncer` 在进入对话 **之前** 就尝试捕获头像，此时屏幕显示的是消息列表而不是对话页面。

但这是次要问题，主要问题是缺少 `screenshot_element` 方法。

---

## 验证：sync_service 是如何获取 UI 树的？

搜索 `sync_service.py` 中的相关代码：

```python
# sync_service.py 第 1677 行
tree = await self.wecom.adb.get_ui_tree()
```

等等！这说明 `ADBService` 应该有 `get_ui_tree` 方法，但我搜索时没找到。

让我重新检查...

**可能的情况**：

1. `get_ui_tree` 方法可能在运行时动态添加（monkeypatch）
2. 或者方法名拼写不同
3. 或者方法在其他文件中定义

---

## 第二层问题：screenshot_element 方法

即使能获取到 UI 树，还有第二个问题：

```python
# avatar.py 第 251-263 行
if hasattr(self._wecom, 'screenshot_element'):
    bounds_str = f"[{avatar_bounds[0]},{avatar_bounds[1]}][{avatar_bounds[2]},{avatar_bounds[3]}]"
    await self._wecom.screenshot_element(bounds_str, str(filepath))
else:
    await self._log("ERROR", f"screenshot_element method not found on wecom_service")
```

搜索结果显示：`WeComService` **没有** `screenshot_element` 方法。

所以即使能找到头像位置，也无法截图保存。

---

## 问题根因总结

| 问题                           | 说明                               | 严重度        |
| ------------------------------ | ---------------------------------- | ------------- |
| ~~缺少 `get_ui_tree` 方法~~    | ~~`AvatarManager` 无法获取 UI 树~~ | ✅ 已确认存在 |
| 缺少 `screenshot_element` 方法 | `AvatarManager` 无法截取头像       | 🔴 阻塞性     |
| 捕获时机错误                   | 在进入对话前尝试捕获（次要问题）   | 🟡 影响效果   |

**主要阻塞问题**: `WeComService` 缺少 `screenshot_element` 方法，导致即使能找到头像位置也无法保存。

## 解决方案

### 方案 1: 在 WeComService 中添加缺失的方法

```python
# wecom_service.py

async def get_ui_tree(self):
    """获取 UI 树"""
    state = await self.adb.adb.get_state()  # DroidRun 的 get_state
    return state.get('ui_tree') or state  # 返回 UI 树

async def screenshot_element(self, bounds_str: str, output_path: str):
    """截取指定区域的屏幕"""
    import re
    from PIL import Image
    from io import BytesIO

    # 解析 bounds
    match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
    if not match:
        raise ValueError(f"Invalid bounds format: {bounds_str}")

    x1, y1, x2, y2 = map(int, match.groups())

    # 截取全屏
    _, image_bytes = await self.adb.take_screenshot()

    # 裁剪
    img = Image.open(BytesIO(image_bytes))
    cropped = img.crop((x1, y1, x2, y2))
    cropped.save(output_path)
```

### 方案 2: 修改 AvatarManager 使用现有方法

修改 `AvatarManager` 直接使用 DroidRun 的 `get_state()` 和 `take_screenshot()`：

```python
# avatar.py - _try_capture_once 方法

async def _try_capture_once(self, name: str) -> Optional[Path]:
    try:
        # 使用 DroidRun 的 get_state
        if hasattr(self._wecom, 'adb') and hasattr(self._wecom.adb, 'adb'):
            state = await self._wecom.adb.adb.get_state()  # DroidRun
            tree = state  # 或 state.get('ui_tree')
        else:
            return None

        # 查找头像
        avatar_bounds = await self._find_avatar_in_tree(tree, name)
        if not avatar_bounds:
            return None

        # 使用 take_screenshot 截图并裁剪
        if hasattr(self._wecom.adb, 'take_screenshot'):
            _, image_bytes = await self._wecom.adb.take_screenshot()
            # 裁剪保存...
```

---

## 推荐操作

1. **首选方案 1**: 在 `WeComService` 中添加 `get_ui_tree` 和 `screenshot_element` 方法
2. 这样可以保持 `AvatarManager` 代码简洁，且其他组件也可以使用这些方法
3. 同时修复捕获时机问题（移到进入对话之后）

---

## 相关文件

| 文件                               | 说明                                     |
| ---------------------------------- | ---------------------------------------- |
| `services/user/avatar.py`          | AvatarManager - 调用不存在的方法         |
| `services/wecom_service.py`        | WeComService - 缺少必要方法              |
| `services/adb_service.py`          | ADBService - 需要确认 get_ui_tree 存在性 |
| `services/sync/customer_syncer.py` | 调用入口                                 |

---

## ✅ 修复实现

**日期**: 2026-01-18

### 修改的文件

#### `src/wecom_automation/services/wecom_service.py` (第 543-620 行)

添加了两个新方法：

1. **`screenshot_element(bounds_str: str, output_path: str) -> bool`** (第 543-606 行)
   - 截取指定边界的 UI 元素
   - 解析边界格式: `[x1,y1][x2,y2]`
   - 使用 `adb.take_screenshot()` 获取全屏截图
   - 使用 PIL 裁剪到指定边界
   - 保存到输出路径

2. **`get_ui_tree(refresh: bool = True) -> Optional[Any]`** (第 608-620 行)
   - 便捷方法，委托给 `adb.get_ui_tree()`
   - 使 AvatarManager 可以直接从 WeComService 获取 UI 树

### 修复效果

- ✅ `AvatarManager._try_capture_once()` 现在可以调用 `self._wecom.screenshot_element()`
- ✅ AvatarManager 可以使用 `self._wecom.get_ui_tree()` 获取 UI 树
- ✅ 头像捕获功能现在应该可以正常工作

### 代码示例

```python
# WeComService 中的新方法
async def screenshot_element(self, bounds_str: str, output_path: str) -> bool:
    """截取指定边界的 UI 元素并保存"""
    # 解析边界
    match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
    x1, y1, x2, y2 = map(int, match.groups())

    # 截图并裁剪
    _, image_bytes = await self.adb.take_screenshot()
    full_image = Image.open(BytesIO(image_bytes))
    cropped = full_image.crop((x1, y1, x2, y2))

    # 保存
    cropped.save(output_path)
    return True
```

### 后续步骤

1. ✅ 代码已修改
2. ⏳ 需要测试头像捕获功能是否正常工作
3. ⏳ 如有必要，调整捕获时机（移到进入对话之后）
