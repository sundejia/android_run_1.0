# 点击搜索图标：`followup_test` 可用 vs 主流程不可用（对比分析）

## 背景

你反馈：`followup_test/test_search_followup.py` 中“点击右上角搜索图标”可用，但在主流程中点击搜索图标不行。

在当前仓库里，主流程的“补刀（通过搜索进入聊天）”实现位于：

- `wecom-desktop/backend/servic../03-impl-and-arch/executor.py`（`FollowupExecutor._step1_click_search()`）

测试脚本实现位于：

- `followup_test/test_search_followup.py`（`SearchFollowupTest.step1_click_search()`）

两者的代码结构非常接近，差异主要来自 **运行上下文 / UI 缓存是否已初始化 / 点击定位策略的可靠性**。

---

## 结论摘要（高概率根因）

即使两边“算法看起来一样”，主流程更容易失败的原因通常不是“点的代码不同”，而是：

- **主流程触发点击时不一定在同一页面**（例如仍在聊天页、或顶部栏形态不同），导致“按文本找 search/搜索”找不到；接着走坐标兜底，但坐标点在了错误位置或被遮挡。
- **坐标兜底依赖屏幕尺寸**，而屏幕尺寸读取依赖 `raw_tree_cache.bounds`；如果 **点击前没有先成功 `get_state()`** 让 `raw_tree_cache` 有效，可能用默认 1080×2400 推算坐标，遇到异形分辨率/沉浸式状态栏时偏差更大。
- **搜索图标在 UI tree 内经常没有 text/desc/resourceId 的 “search” 字样**（很多版本是纯 ImageView），因此“按文本找 search/搜索”天然不稳定，最后全靠坐标。

---

## 两边实现对比

### 1) 定位策略

**测试脚本**（`followup_test/test_search_followup.py`）：

- 方法1：遍历 UI tree，按关键词匹配 `text/contentDescription/resourceId` 包含 `search/搜索/Search`
- 方法2：按屏幕比例坐标点击（`0.82w, 0.055h`）

**主流程补刀执行器**（`wecom-desktop/backend/servic../03-impl-and-arch/executor.py`）：

- 同样是 方法1（UI tree 关键词）→ 方法2（比例坐标兜底）

**关键点**：两者“看起来一样”，但方法1在真实设备上经常命中率很低（搜索图标可能没有任何关键词），实际主要依赖方法2。

---

### 2) 屏幕尺寸的获取时机（影响坐标兜底精度）

两边的模式都类似：

- 先从 `adb.raw_tree_cache.bounds` 读取屏幕尺寸
- 如果读不到，就使用默认值（测试类/执行器里都是 1080×2400）
- 然后才调用 `get_state()` 刷新 UI tree

这会带来一个隐患：

- 如果 `raw_tree_cache` 在此时还是空的，那么屏幕尺寸会落到默认值；
- 对 1080×2400 设备可能“误打误撞还能点中”，但对其他分辨率/状态栏高度变化更明显的设备会更容易点偏。

**建议**（如果你要修主流程点击失败）：把“获取屏幕尺寸”放到一次 `get_state()` 之后，确保 `raw_tree_cache.bounds` 是最新的。

---

### 3) 主流程的运行上下文更复杂（页面不一致概率更高）

测试脚本通常是你手动保证：

- 已经在“消息列表”首页
- 右上角就是搜索图标

而主流程（特别是跟实时回复/扫描串起来时）会存在更多不确定性：

- 可能刚从聊天页返回但页面还没稳定
- 可能在“私聊列表”而不是“消息首页”，顶部栏布局不同
- 可能弹出输入法/弹窗遮挡顶部区域

这些都会让“坐标点击右上角”变得不可靠（点击落点被遮挡/点击到别的按钮）。

---

## 实施的解决方案（已完成）

### 新增方法 0：基于 resourceId 的稳定匹配

根据分析中的"建议 3"，已在主流程 `FollowupExecutor._step1_click_search()` 中新增**方法 0**，作为最高优先级的定位策略：

```python
# 方法0（新增/优先）：按 resourceId 在 clickable cache 里找搜索按钮（最稳定）
SEARCH_ICON_RESOURCE_ID = "com.tencent.wework:id/ngq"

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
    # ... 详见 executor.py
```

**实现细节**：

1. **优先使用 `clickable_elements_cache`**：该缓存包含 `index`，可直接调用 `tap_by_index()`，比坐标点击更稳定
2. **resourceId 精确匹配**：`com.tencent.wework:id/ngq` 是搜索按钮的固定 ID
3. **className 回退机制**：如果 className 不匹配，会回退到只按 resourceId 查找
4. **bounds 验证**：确保元素的 bounds 有效才返回

**点击顺序**：

- 方法 0（resourceId + index，最稳定）→ 方法 1（UI tree 文本搜索）→ 方法 2（比例坐标兜底）

### 配合的改进

1. **强制刷新 UI**：在方法 0 执行前先调用 `_refresh_ui()`，确保 `clickable_elements_cache` 是最新的
2. **bounds 兼容性**：`_get_element_center()` 同时支持 `bounds` 和 `boundsInScreen` 字段
3. **新增测试脚本**：
   - `followup_test/test_click_search_by_resource.py` - 独立测试 resourceId 匹配
   - `followup_test/get_ui_tree.py` - UI 树导出工具

### 测试验证

- 所有 391 个单元测试通过
- `test_click_search_by_resource.py` 可在真实设备上验证 resourceId 匹配逻辑

---

## 辅助工具

仓库新增脚本：

- `followup_test/get_ui_tree.py` - 导出当前页面 UI tree
- `followup_test/test_click_search_by_resource.py` - 测试 resourceId 匹配

示例：

```bash
# 导出 UI tree
uv run followup_test/get_ui_tree.py --serial <你的设备序列号> --out followup_test/ui_tree_now.json

# 测试搜索按钮点击
uv run followup_test/test_click_search_by_resource.py --serial <你的设备序列号>
```

---

## 变更日志

- **2025-02-05**: 实施方法 0（resourceId 匹配），解决主流程点击搜索图标不稳定的问题
