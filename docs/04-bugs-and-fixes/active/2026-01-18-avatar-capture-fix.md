# 头像捕获功能修复 - 双策略方法

**修改日期**: 2026-01-18
**状态**: ✅ 已完成
**相关文件**: `src/wecom_automation/services/user/avatar.py`

---

## 问题回顾

头像捕获功能之前失败的根本原因是：

1. `WeComService` 缺少 `screenshot_element` 方法
2. `AvatarManager._find_avatar_in_tree()` 的查找策略不够可靠

## 修复方案

### 1. 添加 `screenshot_element` 方法

已在 `WeComService` 中添加（第 543-606 行）：

- 解析边界格式 `[x1,y1][x2,y2]`
- 使用 `adb.take_screenshot()` 获取全屏截图
- 使用 PIL 裁剪到指定区域并保存

### 2. 重写头像查找逻辑 - 双策略方法

更新了 `AvatarManager._find_avatar_in_tree()` 方法（第 303-513 行），使用两种策略：

#### 策略 1: 基于节点属性的直接查找（原有方法）

**原理**:

- 查找包含用户名称的节点
- 在同一行中查找符合头像特征的节点：
  - 资源 ID 包含: "avatar", "photo", "icon", "head", "portrait", "profile"
  - 类名包含: "imageview", "image", "avatar", "icon", "photo"
  - 位于左侧 (x1 < 200)
  - 尺寸合理 (40-150px)
  - 接近正方形 (宽高比 0.7-1.3)
  - 与用户名在同一行 (Y 坐标差距 < 100)

**优点**: 当 UI 节点有明确的资源 ID 或类名时，非常准确
**缺点**: 依赖 WeCom UI 的具体实现，可能因版本更新而失效

#### 策略 2: 基于位置推断的方法（新方法）

**原理**:

1. 找到 RecyclerView 列表容器，排除侧边栏
2. 查找用户名候选节点，过滤掉非用户文本（时间戳、按钮等）
3. 找到包含目标用户名的行容器（RelativeLayout/LinearLayout）
4. 基于行容器和用户名位置推断头像位置：
   ```python
   avatar_size = int(row_h * 0.58)  # 头像大小为行高的 58%
   avatar_x1 = cx1 + 56             # 左侧偏移 56 像素
   avatar_y1 = cy1 + (row_h - avatar_size) // 2  # 垂直居中
   ```

**优点**:

- 不依赖具体的节点属性
- 基于 UI 布局规律，更通用
- 参数经过测试验证，可以正确捕获头像

**缺点**:

- 如果 UI 布局发生较大变化可能需要调整参数

### 策略执行顺序

```
1. 尝试策略 1（节点属性查找）
   ↓ 失败
2. 尝试策略 2（位置推断）
   ↓ 失败
3. 返回 None（使用默认头像）
```

## 测试验证

### 测试代码

创建了 `test_avatar_capture.py` 用于测试头像捕获功能。

### 测试结果

使用策略 2 的位置推断方法，测试代码可以成功捕获头像：

- ✅ 正确识别用户名
- ✅ 正确推断头像位置
- ✅ 成功截图并保存

### 关键参数

经过测试验证的参数：

- `avatar_size = row_h * 0.58` - 头像大小为行高的 58%
- `avatar_x1 = cx1 + 56` - 左侧偏移 56 像素
- `avatar_y1 = cy1 + (row_h - avatar_size) // 2` - 垂直居中

## 代码修改

### 文件: `src/wecom_automation/services/user/avatar.py`

**修改内容**:

- 重写了 `_find_avatar_in_tree()` 方法（第 303-513 行）
- 整合了两种策略
- 保留了详细的 DEBUG 日志

**关键代码片段**:

```python
async def _find_avatar_in_tree(self, tree: Any, name: str) -> Optional[Tuple[int, int, int, int]]:
    """
    使用两种策略：
    1. 基于节点属性的直接查找（原有方法）
    2. 基于用户名位置的推断方法（新方法，更可靠）
    """
    # ... 策略 1 代码 ...

    # ... 策略 2 代码 ...
    if container:
        cx1, cy1, cx2, cy2 = container['bounds']
        row_h = cy2 - cy1
        avatar_size = int(row_h * 0.58)
        avatar_x1 = cx1 + 56
        avatar_y1 = cy1 + (row_h - avatar_size) // 2
        return (avatar_x1, avatar_y1, avatar_x1 + avatar_size, avatar_y1 + avatar_size)
```

## 日志输出

新的策略会生成详细的 DEBUG 日志：

```
[DEBUG] _find_avatar_in_tree: searching for 张三
[DEBUG] Collected 1523 nodes from UI tree
[DEBUG] Trying Strategy 1: Direct node attribute search
[DEBUG] Found exact name match: '张三'
[DEBUG] Name position: x=[200,350], y=[345,380]
[DEBUG] Strategy 2 succeeded: Inferred avatar position
[DEBUG]    Name bounds: [200,345][350,380]
[DEBUG]    Inferred avatar: [56,346][114,404]
[DEBUG]    Avatar size: 58x58
```

## 向后兼容性

- ✅ 保留了原有的策略 1，确保在 UI 节点属性明确时仍然有效
- ✅ 新增策略 2 作为备用，提高成功率
- ✅ 不影响现有 API 和调用方式

## 后续建议

1. **监控日志** - 观察生产环境中哪种策略更常成功
2. **调整参数** - 如果 WeCom UI 更新，可能需要微调参数
3. **考虑动态检测** - 未来可以基于实际捕获效果动态调整参数

## 相关文档

- 根因分析: `docs/04-bugs-and-fixes/active/01-18-avatar-capture-root-cause.md`
- 失败分析: `docs/04-bugs-and-fixes/active/01-18-avatar-capture-failure-analysis.md`
- 调试指南: `docs/04-bugs-and-fixes/active/01-18-avatar-debug-guide.md`
- 测试代码: `test_avatar_capture.py`
