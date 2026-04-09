# Avatar 头像保存流程分析

## 概述

Avatar（头像）保存是在同步聊天列表时，为每个用户捕获并缓存其头像图片的过程。

## 日志解读

根据截图中的日志，以下是每条日志的含义：

| 日志级别   | 日志内容                                                  | 含义                                             |
| ---------- | --------------------------------------------------------- | ------------------------------------------------ |
| ⚠️ WARNING | `X Position inference failed for: '孙德家 (苏南老师...)'` | 基于位置的头像推断失败，无法找到该用户的头像位置 |
| ℹ️ INFO    | `Candidates found: ['A大头不磕恋爱~', '@WeChat', ...]`    | 列出在UI中找到的用户名候选项（用于调试）         |
| ℹ️ INFO    | `Scroll attempt 3/3`                                      | 第3次（共3次）滚动尝试                           |
| ⚠️ WARNING | `scroll_up not available`                                 | scroll_up 方法不可用，无法滚动列表               |
| ℹ️ INFO    | `Searching for avatar: 孙德家 (苏南老师...)`              | 开始搜索指定用户的头像                           |
| ℹ️ INFO    | `Collected 81 UI nodes`                                   | 从 UI 树中收集了 81 个节点                       |
| ℹ️ INFO    | `Using position-based inference`                          | 使用基于位置推断的方法来定位头像                 |
| ℹ️ INFO    | `Found chat list container`                               | 找到聊天列表容器（RecyclerView/ListView）        |
| ℹ️ INFO    | `Restricted to list: 46 nodes`                            | 将搜索范围限制在列表容器内（46个节点）           |
| ⚠️ WARNING | `X All attempts failed for: 孙德家 (苏南老师...)`         | 所有尝试都失败了，无法捕获该用户的头像           |
| ⚠️ WARNING | `No default avatar found`                                 | 没有找到默认头像可以使用                         |

## Avatar 保存流程图

```
开始捕获头像
      ↓
[检查缓存] → 已缓存? → 是 → 返回缓存路径
      ↓ 否
[获取 UI 树]
      ↓
[收集所有 UI 节点]
      ↓
[查找聊天列表容器]
      ↓
[限制搜索范围到列表内]
      ↓
[查找用户名候选项]
      ↓
[匹配目标用户名] → 找到? → 否 → 滚动重试 (最多3次)
      ↓ 是                         ↓ 仍然失败
[基于位置推断头像坐标]            [使用默认头像]
      ↓
[截图保存头像]
      ↓
返回头像路径
```

## 详细步骤解析

### 1. 缓存检查 (`is_cached`)

```python
# 检查 avatars 目录下是否已存在该用户的头像
# 支持格式: avatar_{name}.png, avatar_{index}_{name}.png
```

### 2. 获取 UI 树 (`_try_capture_once`)

```python
# 从设备获取当前界面的 UI 层次结构
tree = await self._wecom.get_ui_tree()
```

### 3. 查找头像位置 (`_find_avatar_in_tree`)

这是核心算法，使用**基于位置推断**的方法：

#### 步骤 A: 找到聊天列表容器

```python
# 查找 RecyclerView 或 ListView
# 条件: y1 > 200 (排除顶部导航栏)
#       width > 500 (主要内容区域)
```

#### 步骤 B: 筛选用户名候选项

```python
# 过滤条件:
# - 文本长度 > 1
# - 不是 UI 元素文本 (如 "微信", "搜索", "100%")
# - 不包含时间戳 (如 ":", "AM", "PM")
# - x1 > 150 (留出头像空间)
# - width < 500 (不是太宽的元素)
```

#### 步骤 C: 匹配目标用户

```python
# 尝试精确匹配和部分匹配
if user_text == name or name in user_text or user_text in name:
    target_user = user
```

#### 步骤 D: 推断头像坐标

```python
# 基于行容器计算头像位置
avatar_size = int(row_height * 0.58)  # 头像占行高的 58%
avatar_x1 = container_x1 + 56         # 左边距 56px
avatar_y1 = container_y1 + (row_height - avatar_size) // 2  # 垂直居中
```

### 4. 截图保存 (`screenshot_element`)

```python
# 使用计算出的坐标截取头像区域
await self._wecom.screenshot_element(bounds_str, str(filepath))
# 保存到: avatars/avatar_{name}.png
```

### 5. 失败回退 (`_use_default`)

```python
# 如果所有尝试失败，复制默认头像
shutil.copy(default_avatar, f"avatar_{name}.png")
```

## 失败原因分析

根据日志，用户 "孙德家 (苏南老师...)" 的头像捕获失败的可能原因：

1. **用户名匹配失败**
   - 候选列表 `['A大头不磕恋爱~', '@WeChat', '26 mins ago', 'agony', '@WeChat']` 中没有匹配项
   - 目标用户可能不在当前可见的聊天列表中

2. **滚动失败**
   - `scroll_up not available` 表示滚动方法不可用
   - 无法滚动到目标用户所在的位置

3. **没有默认头像**
   - `No default avatar found` 表示 `avatars/avatar_default.png` 不存在
   - 无法使用后备方案

## 文件结构

```
avatars/
├── avatar_default.png          # 默认头像（必需）
├── avatar_张三.png             # 用户张三的头像
├── avatar_李四.png             # 用户李四的头像
└── avatar_孙德家.png           # 用户孙德家的头像（如果捕获成功）
```

## 相关代码

| 文件                                             | 描述                                                         |
| ------------------------------------------------ | ------------------------------------------------------------ |
| `src/wecom_automation/services/user/avatar.py`   | AvatarManager 类，头像捕获核心逻辑                           |
| `src/wecom_automation/services/wecom_service.py` | WeComService，提供 `get_ui_tree()` 和 `screenshot_element()` |

## 优化建议

1. **添加默认头像文件**
   - 确保 `avatars/avatar_default.png` 存在

2. **改进用户名匹配**
   - 处理括号和特殊字符
   - 支持模糊匹配

3. **增加滚动可靠性**
   - 确保 `scroll_up` 方法可用
   - 增加滚动等待时间
