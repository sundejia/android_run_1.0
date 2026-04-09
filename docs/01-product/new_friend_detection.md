# 新好友检测功能方案

## 背景

在 FollowUp 实时回复功能中，新加的好友没有红点标记，但需要主动点进去与他们聊天。这些新好友的特征是聊天列表中的消息预览包含特定的欢迎语。

## 需求描述

- **目标**: 检测新加的好友，即使没有红点也能识别并进入聊天
- **识别标志**:
  - 英文系统消息: `"You have added XXX as your WeCom co..."`
  - 中文欢迎语: `"感谢您信任并选择WELIKE，未来我将会..."`

## 技术方案

### 1. 检测逻辑

在私聊列表扫描时，除了检测红点（unread指示器）外，还需要检测消息预览是否包含欢迎语关键词。

**欢迎语关键词候选**:

- `"You have added"` (英文添加好友系统消息)
- `"as your WeCom"` (英文添加好友系统消息)
- `"感谢您信任并选择WELIKE"` (中文欢迎语)
- `"未来我将会"` (中文欢迎语)
- 或其他可配置的关键词

### 2. 实现路径

```
Phase 1: 测试验证 (test_new_friend_detection.py)
   ↓
Phase 2: 集成到 FollowUp Scanner
   ↓
Phase 3: 触发自动回复流程
```

### 3. UI 元素分析

需要从聊天列表的每一行中提取：

- 用户名
- 消息预览文本 (`message_preview`)
- 判断消息预览是否包含欢迎语关键词

### 4. 数据结构

```python
@dataclass
class NewFriendIndicator:
    """新好友指示器"""
    user_name: str
    message_preview: str
    is_new_friend: bool  # 是否为新好友（含欢迎语）
    welcome_keyword: str  # 匹配到的欢迎语关键词
```

### 5. 配置项

```python
NEW_FRIEND_WELCOME_KEYWORDS = [
    "感谢您信任并选择WELIKE",
    "未来我将会",
    # 可扩展其他关键词
]
```

## 测试计划

### Phase 1: 测试代码

创建 `test_new_friend_detection.py`：

1. 连接设备
2. 切换到私聊列表
3. 获取 UI 树
4. 解析每一行的消息预览
5. 检测是否包含欢迎语关键词
6. 输出检测结果

**测试目标**:

- 验证 `message_preview` 字段能正确获取
- 验证欢迎语关键词能被正确识别
- 确认 UI 元素的 resourceId 模式

### Phase 2: 集成到主线

若测试成功，将逻辑集成到：

- `backend/servic../03-impl-and-arch/scanner.py` - 扫描逻辑
- `ui_parser.py` - 添加欢迎语检测方法

## 预期效果

1. FollowUp 扫描时能识别新好友
2. 新好友会被加入待处理队列
3. 系统会主动进入新好友聊天并发送欢迎/回复消息

## 文件清单

| 文件                                           | 描述              |
| ---------------------------------------------- | ----------------- |
| `test_new_friend_detection.py`                 | 测试脚本          |
| `do../01-product/new_friend_detection.md`      | 本方案文档        |
| `backend/servic../03-impl-and-arch/scanner.py` | 待修改 - 扫描逻辑 |
| `src/wecom_automation/services/ui_parser.py`   | 待修改 - UI解析   |

## 下一步

1. ✅ 创建方案文档
2. ✅ 编写测试代码 `test_new_friend_detection.py`
3. ✅ 运行测试验证 UI 元素获取
4. ✅ 集成到主线代码

### 测试验证结果 (2026-01-20)

**测试状态**: ✅ 通过

**检测到的新好友**:

- muhey，(关键词: 感谢您信任并选择WELIKE)
- 章卷卷 (关键词: 感谢您信任并选择WELIKE)

**结论**: 消息预览 (`message_preview`) 字段可以正确获取，欢迎语关键词检测有效。

### 主线集成完成 (2026-01-20)

**修改的文件**:

| 文件                                                                   | 修改内容                                                                            |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `src/wecom_automation/services/user/unread_detector.py`                | 添加 `is_new_friend` 字段、`is_priority()` 方法、`NEW_FRIEND_WELCOME_KEYWORDS` 常量 |
| `src/wecom_automation/services/sync_service.py`                        | 使用 `is_priority()` 替代 `unread_count > 0` 进行高优先级用户检测                   |
| `wecom-desktop/backend/servic../03-impl-and-arch/scanner.py`           | 更新 `_detect_first_page_unread` 方法使用 `is_priority()`                           |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 更新 `_detect_first_page_unread` 方法使用 `is_priority()`                           |

**核心逻辑**:

```python
# 高优先级用户判断
def is_priority(self) -> bool:
    """
    判断是否为高优先级用户

    高优先级条件：
    1. 有未读消息（红点）
    2. 或者是新好友（消息预览包含欢迎语）
    """
    return self.unread_count > 0 or self.is_new_friend

# 新好友欢迎语关键词
NEW_FRIEND_WELCOME_KEYWORDS = (
    # 英文关键词 - 添加新好友系统消息
    "You have added",
    "as your WeCom",
    # 中文关键词 - 欢迎语
    "感谢您信任并选择WELIKE",
    "未来我将会",
    "感谢您信任",
    "选择WELIKE",
)
```

**预期行为**:

- Sync 流程：新好友与红点用户一样被识别为高优先级，优先同步
- FollowUp Scanner：新好友会被加入待处理队列，触发自动回复
- Response Detector：新好友会被检测并进入交互等待循环
