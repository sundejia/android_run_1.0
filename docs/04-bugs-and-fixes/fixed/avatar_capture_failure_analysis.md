# 头像捕获失败原因分析

## ✅ 已修复

**修复日期**: 2026-01-19

**修复方案**: 将头像捕获时机从 "进入对话前的独立步骤" 改为 "在点击用户时、用户可见时捕获"

**修改的文件**:

- `src/wecom_automation/services/wecom_service.py` - 添加 `pre_click_callback` 参数
- `src/wecom_automation/services/sync/customer_syncer.py` - 在 `_enter_conversation` 中使用回调

## 问题概述

在同步流程中，部分用户无法正确获得头像。根据日志分析，主要表现为：

```
[WARNING] [AVATAR] [avatar] ✗ Position inference failed for: '孙德家 (苏南老师（12-21点在线，有事电话联系）)'
[INFO] [AVATAR] [avatar] Candidates found: ['A大头不磕恋爱~', '@WeChat', '26 mins ago', 'agony', '@WeChat']
[WARNING] [AVATAR] [avatar] ✗ All attempts failed for: 孙德家 (苏南老师（12-21点在线，有事电话联系）)
[WARNING] [AVATAR] [avatar] No default avatar found
```

## 失败原因分析

### 原因 1: 用户不在当前可见列表中 ⭐ 最常见

**症状**: 候选列表中没有目标用户

**场景**:

- 聊天列表很长，目标用户在屏幕外
- 用户在列表下方，需要滚动才能看到

**日志特征**:

```
Candidates found: ['A大头不磕恋爱~', '@WeChat', '26 mins ago', 'agony', '@WeChat']
# 目标用户 "孙德家" 不在候选列表中
```

**代码位置**: `avatar.py` 第 364-372 行

```python
# Find the target user
target_user = None
for user in user_name_candidates:
    user_text = user['text'].split('@')[0].split('[')[0].strip()
    # Try exact match first, then partial match
    if user_text == name or name in user_text or user_text in name:
        target_user = user
        break
```

### 原因 2: 滚动功能不可用

**症状**: `scroll_up not available`

**原因**:

- `WeComService` 没有 `scroll_up` 方法
- 或者在某些上下文中该方法不可用

**日志特征**:

```
[WARNING] [AVATAR] [avatar] scroll_up not available
```

**代码位置**: `avatar.py` 第 176-180 行

```python
if hasattr(self._wecom, 'scroll_up'):
    await self._wecom.scroll_up()
else:
    await self._log("WARNING", f"[avatar] scroll_up not available")
```

### 原因 3: 用户名匹配失败

**症状**: 用户在列表中但匹配不上

**场景**:

- 用户名包含特殊字符 `()（）[]【】`
- 用户名有多个变体（如 "张三" vs "张三@WeChat"）
- UI显示的名字与数据库中的名字不一致

**示例**:

```
目标用户名: "孙德家 (苏南老师（12-21点在线，有事电话联系）)"
UI显示名称: "孙德家" 或 "孙德家 (苏南老师..."  # 可能被截断
```

**代码问题**: 当前匹配逻辑

```python
user_text = user['text'].split('@')[0].split('[')[0].strip()
# 问题: 没有处理中文括号 （）
# 也没有处理 name 参数本身可能带括号的情况
```

### 原因 4: 没有默认头像

**症状**: 所有尝试失败后，无法使用默认头像

**日志特征**:

```
[WARNING] [AVATAR] [avatar] No default avatar found
```

**代码位置**: `avatar.py` 第 258-264 行

```python
if not self._default_avatar or not self._default_avatar.exists():
    default_path = self._avatars_dir / "avatar_default.png"
    if not default_path.exists():
        await self._log("WARNING", f"[avatar] No default avatar found")
        return None
```

### 原因 5: UI元素被错误过滤

**症状**: 候选列表中有 `@WeChat`、`26 mins ago` 等非用户名元素

**问题**: 过滤规则不够严格，导致时间戳和渠道标签混入候选列表

**代码位置**: `avatar.py` 第 354-359 行

```python
# Identify user name candidates
if text and len(text) > 1 and text not in SKIP_TEXTS:
    # Basic timestamp and date filtering
    if not any(ts in text for ts in [":", "AM", "PM", "202", "Yesterday"]) and (x2 - x1) < 500:
        if x1 > 150:  # Leave room for avatar
            user_name_candidates.append(...)
```

## 失败场景流程图

```
开始捕获头像 (用户 "孙德家")
        ↓
[获取 UI 树]
        ↓
[收集候选用户名]
        ↓
候选列表: ['A大头不磕恋爱~', '@WeChat', '26 mins ago', ...]
        ↓
[尝试匹配 "孙德家"] → 不在列表中 ❌
        ↓
[滚动尝试 1/3] → scroll_up not available ❌
        ↓
[滚动尝试 2/3] → 失败 ❌
        ↓
[滚动尝试 3/3] → 失败 ❌
        ↓
[使用默认头像] → avatar_default.png 不存在 ❌
        ↓
返回 None (头像捕获失败)
```

## 修复建议

### 修复 1: 改进用户名匹配逻辑

```python
def normalize_name(name: str) -> str:
    """规范化用户名，移除括号和后缀"""
    # 移除各种括号及其内容
    name = re.sub(r'[\(（\[【].*?[\)）\]】]', '', name)
    # 移除 @ 后缀
    name = name.split('@')[0]
    # 清理空白
    return name.strip()

# 使用规范化后的名称进行匹配
normalized_target = normalize_name(name)
for user in user_name_candidates:
    normalized_user = normalize_name(user['text'])
    if normalized_target in normalized_user or normalized_user in normalized_target:
        target_user = user
        break
```

### 修复 2: 提供默认头像

在 `avatars` 目录中创建 `avatar_default.png` 文件，作为捕获失败时的后备方案。

### 修复 3: 改进滚动逻辑

```python
# 确保在正确的上下文中获取滚动方法
if hasattr(self._wecom, 'adb') and hasattr(self._wecom.adb, 'scroll'):
    await self._wecom.adb.scroll(direction='up')
elif hasattr(self._wecom, 'scroll_up'):
    await self._wecom.scroll_up()
else:
    # 使用 swipe 模拟滚动
    await self._wecom.adb.swipe(540, 800, 540, 400, 300)
```

### 修复 4: 更严格的候选过滤

```python
# 添加更多需要跳过的模式
SKIP_PATTERNS = [
    r'^\d+\s*(mins?|hours?|days?)\s*ago$',  # "26 mins ago"
    r'^@\w+$',  # "@WeChat"
    r'^\d{1,2}:\d{2}$',  # "10:30"
    r'^Yesterday$',
    r'^Today$',
]

def should_skip(text):
    if text in SKIP_TEXTS:
        return True
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            return True
    return False
```

### 修复 5: 先滚动到顶部再捕获

```python
async def capture(self, name: str, max_scroll_attempts: int = 3) -> Optional[Path]:
    # 先尝试滚动到列表顶部
    await self._scroll_to_top()

    # 然后开始向下搜索
    for attempt in range(max_scroll_attempts * 2):
        result = await self._try_capture_once(name)
        if result:
            return result

        # 向下滚动
        await self._scroll_down()
```

## 代码修改建议

### 文件: `src/wecom_automation/services/user/avatar.py`

**位置: 第 364-372 行**

```python
# 现有代码
for user in user_name_candidates:
    user_text = user['text'].split('@')[0].split('[')[0].strip()
    if user_text == name or name in user_text or user_text in name:
        target_user = user
        break

# 建议修改为
def normalize_for_match(text: str) -> str:
    """规范化文本用于匹配"""
    # 移除各种括号及其内容
    text = re.sub(r'[\(（\[【].*', '', text)
    text = text.split('@')[0]
    return text.strip()

target_normalized = normalize_for_match(name)
for user in user_name_candidates:
    user_normalized = normalize_for_match(user['text'])
    if target_normalized == user_normalized or \
       target_normalized in user_normalized or \
       user_normalized in target_normalized:
        target_user = user
        await self._log("INFO", f"[avatar] Found user: '{user['text']}' (matched '{target_normalized}')")
        break
```

## 测试验证

使用 `test_avatar_debug.py` 测试特定用户：

```bash
# 设置 PYTHONPATH
$env:PYTHONPATH = "d:\111\android_run_test-backup\src"

# 测试特定用户
python test_avatar_debug.py --name "孙德家"

# 查看候选列表，分析匹配失败原因
```

## 相关文件

| 文件                                           | 描述                 |
| ---------------------------------------------- | -------------------- |
| `src/wecom_automation/services/user/avatar.py` | AvatarManager 核心类 |
| `test_avatar_debug.py`                         | 头像捕获调试脚本     |
| `test_avatar_output/debug_ui_tree.json`        | UI树调试输出         |

## 优先级

1. 🔴 **高**: 提供默认头像文件（快速修复，确保有后备方案）
2. 🟠 **中**: 改进用户名匹配逻辑（解决大部分匹配失败）
3. 🟡 **低**: 改进滚动逻辑（处理用户不在可见区域的情况）
