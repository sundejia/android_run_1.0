# 消息发送者误识别问题分析

**日期**: 2025-01-31  
**状态**: ✅ 已修复（锚点检测方案）  
**模块**: `ui_parser.py`, `response_detector.py`  
**问题描述**: AI 回复后，在交互等待循环中检测新消息时，将 Agent 之前发送的消息错误识别为客户发送的新消息。

## 问题现象

从日志可以看到：

```
13:58:25 | INFO     | [30624212820052G] ✅ Reply sent (via Sidecar)
13:58:25 | INFO     | [30624212820052G]    ⏳ Waiting for new customer messages (timeout=10s)...
13:58:29 | INFO     | [30624212820052G]    📨 Round 1: Found 1 new customer message(s)
13:58:29 | INFO     | [30624212820052G]    Customer: Hello，我是BOSS上和你联系的猞猁老师...
```

**问题**: 检测到的"新客户消息"内容与 Agent 之前发送的消息完全相同：

```
AGENT: Hello，我是BOSS上和你联系的猞猁老师。我们是全网直播经纪公司，年流水2亿...
↓ 被错误识别为 ↓
CUSTOMER: Hello，我是BOSS上和你联系的猞猁老师。我们是全网直播经纪公司，年流水2亿...
```

## 消息去重机制分析

### 消息签名生成（已废弃 - 已被锚点检测替代）

```python
# response_detector.py - 已删除
def _get_message_signature(self, msg: Any) -> str:
    """生成消息签名用于去重"""
    is_self = getattr(msg, 'is_self', False)
    msg_type = getattr(msg, 'message_type', 'text')
    content = (getattr(msg, 'content', '') or '')[:50]
    timestamp = getattr(msg, 'timestamp', '') or ''
    return f"{is_self}|{msg_type}|{content}|{timestamp}"
```

**签名格式**: `{is_self}|{message_type}|{content前50字符}|{timestamp}`

**问题**: 如果同一条消息的 `is_self` 在两次提取中不一致：

- 第一次: `True|text|Hello，我是BOSS上...|10:30`
- 第二次: `False|text|Hello，我是BOSS上...|10:30`

这两个签名不同，导致同一条消息被识别为"新消息"。

### 交互等待循环流程

```
1. Agent 发送回复
2. 提取当前消息，生成 seen_signatures
3. 等待 3 秒
4. 重新提取消息
5. 比对签名，找出"新消息"
   ↓
   如果 is_self 判断不一致，会产生误判
```

## is_self 判断逻辑分析

### ui_parser.py 中的判断逻辑

```python
# line 1299-1336
# 1. 优先检查头像位置
avatar_on_left = avatar_x is not None and avatar_x < 200
avatar_on_right = avatar_x is not None and avatar_x > screen_width - 200

if avatar_on_left:
    is_self = False  # 头像在左 = 客户消息
elif avatar_on_right:
    is_self = True   # 头像在右 = 客服消息
elif content_x is not None:
    # 2. 无头像时，根据内容位置判断
    # 内容在右半边 → 客服消息 (is_self=True)
    # 内容在左半边 → 客户消息 (is_self=False)
    is_self = content_x > screen_width // 2
else:
    # 3. 兜底：根据气泡位置判断
    center_x = (x1 + x2) // 2
    is_self = center_x > screen_width // 2
```

### 可能导致误判的场景

#### 场景 1: 消息气泡位置变化

```
第一次提取（消息刚发送）：
┌────────────────────────────┐
│                   [消息内容]│  ← content_x = 800 > 540 → is_self=True ✓
│                      头像  │
└────────────────────────────┘

第二次提取（UI 重新渲染后）：
┌────────────────────────────┐
│  [消息内容]                 │  ← content_x = 400 < 540 → is_self=False ✗
│  头像（位置变化）            │
└────────────────────────────┘
```

#### 场景 2: 头像元素未被检测到

```
正常情况：头像在右边 → is_self=True
异常情况：头像元素丢失 → 回退到 content_x 判断 → 可能出错
```

#### 场景 3: 屏幕宽度检测不一致

```
第一次: screen_width = 1080, 中点 = 540
第二次: screen_width = 720, 中点 = 360  ← 如果检测错误
```

日志显示 `Auto-detected screen width: 1080px`，但这是在提取消息时才检测的，可能每次检测结果不一致。

#### 场景 4: 长消息折行导致位置计算错误

长消息可能导致气泡宽度接近全屏，此时：

```python
if width < screen_width * 0.8:
    # 只对小于 80% 屏幕宽度的气泡做位置判断
```

如果消息很长，可能不会进入这个判断，导致 is_self 保持默认值 False。

## 根本原因

**核心问题**: `is_self` 判断依赖于 UI 元素的位置，但这些位置可能因为：

1. UI 重新渲染
2. 消息动画效果
3. 头像元素加载时机
4. 长消息折行

而在两次提取中产生不同结果。

## 影响

1. **重复回复**: 系统误以为客户发了新消息，再次生成并发送回复
2. **对话混乱**: AI 上下文中包含重复/错误的消息
3. **用户体验差**: 可能连续发送多条相似回复

## 修复建议

### 方案 1: 增强签名稳定性（推荐）

在签名中不依赖 `is_self`，改用内容+时间戳：

```python
def _get_message_signature(self, msg: Any) -> str:
    """生成消息签名用于去重 - 不依赖 is_self"""
    msg_type = getattr(msg, 'message_type', 'text')
    content = (getattr(msg, 'content', '') or '')[:80]  # 增加长度
    timestamp = getattr(msg, 'timestamp', '') or ''
    # 不使用 is_self，避免因 UI 变化导致签名不一致
    return f"{msg_type}|{content}|{timestamp}"
```

**风险**: 如果客户确实发送了与 Agent 相同的内容（极少见），会被误过滤。

### 方案 2: 双重验证

在检测到"新消息"后，额外验证：

```python
for msg in current_messages:
    sig = self._get_message_signature(msg)
    is_self = getattr(msg, 'is_self', False)
    content = getattr(msg, 'content', '') or ''

    if not is_self and sig not in seen_signatures:
        # 额外检查：这条消息内容是否与最近发送的回复相同
        if self._is_recent_agent_reply(content, sent_replies):
            self._logger.warning(f"Skipping suspected mis-identified message: {content[:30]}...")
            seen_signatures.add(sig)  # 标记为已见，避免下次再检测
            continue
        new_customer_messages.append(msg)
```

### 方案 3: 增加消息位置缓存

缓存每条消息的位置信息，在二次提取时验证位置是否一致：

```python
class MessagePositionCache:
    def __init__(self):
        self._cache: Dict[str, Tuple[int, bool]] = {}  # content -> (position_x, is_self)

    def validate_is_self(self, content: str, current_is_self: bool, current_x: int) -> bool:
        """验证 is_self 是否与缓存一致"""
        if content in self._cache:
            cached_x, cached_is_self = self._cache[content]
            if cached_is_self != current_is_self:
                # 不一致，使用缓存的值（首次判断通常更准确）
                return cached_is_self
        return current_is_self
```

### 方案 4: 发送后立即记录

在发送回复后，立即将回复内容添加到"已发送"列表，后续检测时直接跳过：

```python
# 在 _send_reply_wrapper 成功后
self._recent_sent_messages.add(reply_content[:80])

# 在检测新消息时
for msg in current_messages:
    content = getattr(msg, 'content', '') or ''
    if content[:80] in self._recent_sent_messages:
        # 这是我们刚发送的消息，跳过
        continue
```

## 相关代码位置

| 功能         | 文件                 | 行号                   |
| ------------ | -------------------- | ---------------------- |
| 消息签名生成 | response_detector.py | ~~986-992~~ （已删除） |
| 交互等待循环 | response_detector.py | 822-923                |
| is_self 判断 | ui_parser.py         | 1298-1336              |
| 提取消息     | ui_parser.py         | 904-1410               |
| 屏幕宽度检测 | ui_parser.py         | 887-902                |

---

## ✅ 修复说明（2025-01-31）

采用**锚点检测（Anchor-based Detection）**方案替换原有签名机制：

### 修复实现

- **MessageTracker 类**：签名 `type|content[:80]`（不含 `is_self`、`timestamp`）
- **processed_signatures**：已处理内容集合，防止重复
- **last_signatures**：带索引 `type|content|idx:N`，追踪位置
- **检测条件**：内容未处理过 **且** 位置未见过 → 新消息

### 修改文件

- `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`
  - 新增 `MessageTracker`
  - 修改 `_interactive_wait_loop` 使用锚点检测
  - 删除 `_get_message_signature`

### 参考

- 实现记录：`do../03-impl-and-arch/experiments/2025-01-31-anchor-detection-and-send-button-enhancement.md`
- 测试脚本：`test_anchor_detection.py`
