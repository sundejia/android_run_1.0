# 补刀搜索输入框检测实现

> 文档创建：2026-02-04
> 状态：已实现

## 背景

在补刀（FollowUp）系统中，搜索用户并发送消息时，输入框检测是关键步骤。本文档记录了输入框检测的实现细节和与测试脚本的一致性。

## 实现方案

### 输入框检测策略

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/executor.py`

`_find_input_field()` 方法使用层级检测策略（优先级从高到低）：

```python
def _find_input_field(self, tree: dict) -> dict | None:
    """查找输入框

    查找策略（与 test_search_followup.py 一致）：
    1. className 包含 EditText
    2. text/resourceId 包含输入框关键词
    """
    input_hints = ("edittext", "input", "输入", "type", "compose", "说点什么")

    def traverse(node: dict, depth: int = 0) -> dict | None:
        if depth > 30:
            return None

        class_name = str(node.get("class", "") or node.get("className", "")).lower()
        text = str(node.get("text", "")).lower()
        rid = str(node.get("resourceId", "")).lower()

        # 方法1: 检查 className 是否包含 EditText
        if "edittext" in class_name or "edit" in class_name:
            return node

        # 方法2: 检查 text/resourceId 中的关键词
        for hint in input_hints:
            if hint in text or hint in rid:
                return node

        for child in node.get("children", []):
            result = traverse(child, depth + 1)
            if result:
                return result
        return None

    return traverse(tree)
```

## 测试脚本一致性

**文件**: `followup_test/test_search_followup.py`

测试脚本使用相同的输入框检测逻辑（lines 151-178）：

```python
def find_input_field(self, tree: Dict) -> Optional[Dict]:
    """查找输入框（复用 wecom_service 的逻辑）"""
    input_hints = ("edittext", "input", "输入", "type", "compose", "说点什么")

    def traverse(node: Dict, depth: int = 0) -> Optional[Dict]:
        if depth > 30:
            return None

        class_name = str(node.get("class", "") or node.get("className", "")).lower()
        text = str(node.get("text", "")).lower()
        rid = str(node.get("resourceId", "")).lower()

        # 检查 class name
        if "edittext" in class_name or "edit" in class_name:
            return node

        # 检查 text/hints
        for hint in input_hints:
            if hint in text or hint in rid:
                return node

        for child in node.get("children", []):
            result = traverse(child, depth + 1)
            if result:
                return result
        return None

    return traverse(tree)
```

## 搜索流程

### 步骤2: 输入搜索关键词

```python
async def _step2_input_search(self, query: str) -> bool:
    """步骤2: 输入搜索关键词

    关键改进：即使找不到输入框也会尝试直接输入，
    因为搜索页面通常自动聚焦到搜索框
    """
    # ... 查找输入框 ...
    input_field = self._find_input_field(tree)
    if input_field:
        # 找到输入框，点击聚焦
        x, y = self._get_element_center(input_field)
        await self._tap(x, y, "输入框")
        await asyncio.sleep(0.5)
    else:
        # 即使找不到输入框，搜索页面通常已自动聚焦，直接输入即可
        self._log("  ⚠️ 未找到输入框UI元素，但搜索页面通常自动聚焦，继续输入...")

    # 输入文本（无论是否找到输入框都尝试输入）
    self._log(f"  输入文本: {query}")
    await self._input_text(query)
    await asyncio.sleep(1)
    return True
```

## 关键特性

### 1. 简洁的检测策略

使用两层检测机制：

1. **className 检测**: 最直接的方法，检查是否包含 "EditText" 或 "edit"
2. **关键词检测**: 检查 text/resourceId 中的常见输入框关键词

### 2. 容错输入机制

即使找不到输入框UI元素，也尝试直接输入：

- 搜索页面通常会自动聚焦到搜索框
- 避免因UI检测失败导致整体流程失败

### 3. 与测试脚本一致

`executor.py` 中的实现与 `test_search_followup.py` 完全一致，确保：

- 测试通过的行为在生产环境中也能工作
- 代码维护简化 - 只需维护一套逻辑

## 测试验证

测试截图位于 `followup_test/` 目录：

- `search_test_01_initial.png` - 初始状态
- `search_test_02_search_clicked.png` - 点击搜索后
- `search_test_03_search_input.png` - 输入搜索词
- `search_test_04_in_chat.png` - 进入聊天
- `search_test_05_message_sent.png` - 消息发送
- `search_test_06_back.png` - 返回列表

## 日志示例

### 成功找到输入框

```
│ 步骤2: 输入搜索关键词                            │
  搜索关键词: [张三]
  查找输入框...
  ✅ 找到输入框:
     - 位置: (540, 150)
     - bounds: {'left': 90, 'top': 120, 'right': 990, 'bottom': 180}
     - className: android.widget.EditText
  输入文本: 张三
  ✅ 搜索关键词输入完成
```

### 未找到输入框但继续执行

```
│ 步骤2: 输入搜索关键词                            │
  搜索关键词: [李四]
  查找输入框...
  ⚠️ 未找到输入框UI元素，但搜索页面通常自动聚焦，继续输入...
  输入文本: 李四
  ✅ 搜索关键词输入完成
```

## 相关文件

| 文件                                                          | 描述             |
| ------------------------------------------------------------- | ---------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/executor.py` | 补刀执行器实现   |
| `followup_test/test_search_followup.py`                       | 补刀搜索测试脚本 |
| `do../01-product/followup-blacklist-integration.md`           | 黑名单集成文档   |

## 参考文档

- [补刀系统流程分析](../03-impl-and-arch/followup-flow-analysis.md)
- [补刀系统改进计划](../03-impl-and-arch/followup-improvement-plan.md)
