# AI 多消息回复功能改进方案

## 概述

目前 AI 系统每次只能生成并发送一条回复消息。本文档探讨多种改进方案，使 AI 能够发送多条消息，提升对话的自然度和互动效果。

---

## 当前限制分析

### 1. 现有代码结构

**文件**: `src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py`

```python
async def get_reply(...) -> Optional[str]:
    """获取AI回复 - 返回单个字符串"""
    # ...
    return output  # 只返回一条消息
```

**文件**: `interfaces.py` - `IAIReplyService` 接口

```python
async def get_reply(...) -> Optional[str]:
    """返回类型是 Optional[str]，只支持单条消息"""
```

### 2. 消息发送流程

```
AI生成回复 → 单条字符串 → send_message() → 发送一条
```

### 3. 限制原因

| 限制点    | 说明                                         |
| --------- | -------------------------------------------- |
| 接口设计  | `get_reply()` 返回 `Optional[str]`，而非列表 |
| AI 提示词 | 未要求生成多条分隔消息                       |
| 发送逻辑  | `send_message()` 只发送一次                  |
| 延迟控制  | 多条消息间无自然延迟                         |

---

## 改进方案

### 方案 A：分隔符拆分（推荐 - 最小改动）

**原理**：让 AI 在回复中使用特殊分隔符，发送前拆分为多条消息。

#### A.1 修改系统提示词

```python
MULTI_MESSAGE_INSTRUCTION = """
When you need to send multiple messages, separate them with |||
Example: "Hello!|||How can I help you?|||Looking forward to your reply!"
Each part will be sent as a separate message.
"""
```

#### A.2 修改回复处理

```python
async def get_replies(
    self,
    message: str,
    context: MessageContext,
    history: Optional[List[Dict[str, Any]]] = None
) -> List[str]:
    """获取AI回复（支持多条）"""
    reply = await self.get_reply(message, context, history)
    if not reply:
        return []

    # 使用分隔符拆分
    SEPARATOR = "|||"
    if SEPARATOR in reply:
        messages = [msg.strip() for msg in reply.split(SEPARATOR) if msg.strip()]
        return messages

    return [reply]
```

#### A.3 修改发送逻辑

```python
async def send_multi_messages(
    self,
    messages: List[str],
    min_delay: float = 1.0,
    max_delay: float = 3.0
) -> List[bool]:
    """发送多条消息，带随机延迟"""
    results = []
    for i, msg in enumerate(messages):
        if i > 0:
            # 消息间随机延迟，模拟真人打字
            delay = random.uniform(min_delay, max_delay)
            await asyncio.sleep(delay)

        success, _ = await wecom.send_message(msg)
        results.append(success)

    return results
```

#### A.4 优点 & 缺点

| 优点     | 缺点                   |
| -------- | ---------------------- |
| 改动最小 | 依赖 AI 正确使用分隔符 |
| 向后兼容 | 分隔符可能出现在内容中 |
| 易于实现 | 需要修改提示词         |

---

### 方案 B：结构化 JSON 回复

**原理**：让 AI 返回 JSON 格式的消息列表。

#### B.1 修改系统提示词

```python
JSON_INSTRUCTION = """
Always respond in JSON format:
{
  "messages": ["First message", "Second message", "..."],
  "delay_seconds": [0, 2, 1.5]
}
If only one message, use: {"messages": ["Your message"]}
"""
```

#### B.2 解析 JSON 回复

```python
import json

def parse_multi_reply(reply: str) -> List[Dict]:
    """解析 JSON 格式的多条回复"""
    try:
        data = json.loads(reply)
        messages = data.get("messages", [])
        delays = data.get("delay_seconds", [])

        # 确保 delays 与 messages 长度匹配
        while len(delays) < len(messages):
            delays.append(2.0)  # 默认延迟

        return [{"text": msg, "delay": delay}
                for msg, delay in zip(messages, delays)]
    except json.JSONDecodeError:
        # 回退到单条消息
        return [{"text": reply, "delay": 0}]
```

#### B.3 优点 & 缺点

| 优点                   | 缺点                 |
| ---------------------- | -------------------- |
| 结构清晰               | AI 可能输出非法 JSON |
| 支持自定义延迟         | 需要额外的解析逻辑   |
| 可扩展（表情、图片等） | 实现复杂度较高       |

---

### 方案 C：接口重构（长期方案）

**原理**：从根本上重新设计接口，支持多消息回复。

#### C.1 新增数据类型

```python
@dataclass
class AIReplyMessage:
    """AI 回复消息"""
    content: str
    message_type: str = "text"  # text, image, voice, etc.
    delay_before_send: float = 0  # 发送前延迟
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AIReplyResult:
    """AI 回复结果"""
    messages: List[AIReplyMessage]
    is_human_request: bool = False
    confidence: float = 1.0
```

#### C.2 新接口定义

```python
class IAIReplyService(ABC):
    @abstractmethod
    async def get_replies(
        self,
        message: str,
        context: MessageContext,
        history: Optional[List[Dict[str, Any]]] = None
    ) -> AIReplyResult:
        """获取AI回复（支持多条）"""
        pass

    # 保留旧接口用于兼容
    async def get_reply(self, message, context, history=None) -> Optional[str]:
        """获取单条回复（兼容接口）"""
        result = await self.get_replies(message, context, history)
        if result.messages:
            return result.messages[0].content
        return None
```

#### C.3 优点 & 缺点

| 优点       | 缺点               |
| ---------- | ------------------ |
| 设计完善   | 改动量大           |
| 类型安全   | 需要更新所有调用方 |
| 可扩展性强 | 实施周期长         |

---

### 方案 D：AI 服务端支持（最灵活）

**原理**：在 AI 服务端实现多消息支持，客户端只需循环发送。

#### D.1 修改 AI 服务响应

```json
{
  "success": true,
  "output": ["Hello!", "How can I help?"],
  "message_count": 2
}
```

#### D.2 客户端处理

```python
async def get_reply(...) -> List[str]:
    # ...
    data = await resp.json()

    if data.get("success"):
        output = data.get("output")
        if isinstance(output, list):
            return output
        return [output] if output else []
    return []
```

---

## 推荐实施路径

### 短期（1-2天）：方案 A

1. 修改系统提示词，添加分隔符指令
2. 添加 `get_replies()` 方法（返回列表）
3. 修改发送逻辑，支持多消息带延迟
4. 现有 `get_reply()` 保持兼容

### 中期（1周）：方案 D

1. 修改 AI 服务端 API 返回格式
2. 客户端适配新格式
3. 添加消息发送策略（延迟、重试）

### 长期（2周+）：方案 C

1. 重构接口定义
2. 更新所有服务实现
3. 添加多媒体消息支持

---

## 详细实现：方案 A

### 任务清单

| 任务   | 文件                 | 内容                                           |
| ------ | -------------------- | ---------------------------------------------- |
| Task 1 | `reply_service.py`   | 添加 `MULTI_MESSAGE_SEPARATOR` 常量            |
| Task 2 | `reply_service.py`   | 修改 `_build_enhanced_prompt()` 添加多消息指令 |
| Task 3 | `reply_service.py`   | 添加 `get_replies()` 方法                      |
| Task 4 | `interfaces.py`      | 添加 `get_replies()` 到接口                    |
| Task 5 | `customer_syncer.py` | 修改使用 `get_replies()` 并循环发送            |
| Task 6 | `scanner.py`         | 修改 FollowUp 使用多消息发送                   |

### 代码示例

**reply_service.py 修改**

```python
class AIReplyService(IAIReplyService):
    # 多消息分隔符
    MULTI_MESSAGE_SEPARATOR = "|||"

    def _build_enhanced_prompt(self) -> str:
        """构建增强的系统提示词"""
        base = self.system_prompt.strip() if self.system_prompt else ""

        human_detection = (
            "If the user wants to switch to human operation, human agent, "
            "or manual service, directly return ONLY the text "
            "'command back to user operation' without any other text."
        )

        multi_message = (
            "You can send multiple messages by separating them with |||. "
            "Example: 'Hello!|||How are you today?|||Let me help you.' "
            "Each part will be sent as a separate message with natural delays. "
            "This makes the conversation feel more natural and human-like."
        )

        parts = [base, human_detection, multi_message]
        return "\n\n".join(p for p in parts if p)

    async def get_replies(
        self,
        message: str,
        context: MessageContext,
        history: Optional[List[Dict[str, Any]]] = None
    ) -> List[str]:
        """获取 AI 回复列表（支持多条消息）"""
        reply = await self.get_reply(message, context, history)
        if not reply:
            return []

        # 检查是否需要转人工
        if self.is_human_request(reply):
            return [reply]

        # 拆分多条消息
        if self.MULTI_MESSAGE_SEPARATOR in reply:
            messages = [
                msg.strip()
                for msg in reply.split(self.MULTI_MESSAGE_SEPARATOR)
                if msg.strip()
            ]
            self._logger.info(f"AI generated {len(messages)} messages")
            return messages

        return [reply]
```

**customer_syncer.py 修改**

```python
async def _send_reply_to_customer(self, ...):
    # ...

    # 获取多条消息
    if hasattr(self._ai_service, 'get_replies'):
        messages = await self._ai_service.get_replies(message_content, context, history)
    else:
        reply = await self._ai_service.get_reply(message_content, context, history)
        messages = [reply] if reply else []

    if not messages:
        return False

    # 检查转人工
    if len(messages) == 1 and self._ai_service.is_human_request(messages[0]):
        self._logger.warning(f"🙋 User {context.customer_name} requested human agent")
        return False

    # 发送多条消息
    all_success = True
    for i, msg in enumerate(messages):
        if i > 0:
            # 消息间延迟
            delay = random.uniform(1.5, 3.0)
            await asyncio.sleep(delay)

        success = False
        if self._sidecar_client:
            success, _ = await self._send_via_sidecar(msg, context)
        elif hasattr(self._wecom, 'send_message'):
            success, _ = await self._wecom.send_message(msg)

        if success:
            await self._store_sent_message(msg, context)
        else:
            all_success = False

    return all_success
```

---

## 延迟策略

### 模拟真人打字的延迟

```python
import random

def calculate_typing_delay(message: str) -> float:
    """根据消息长度计算模拟打字延迟"""
    # 平均打字速度：每分钟 200 字符
    chars_per_second = 3.3
    base_delay = len(message) / chars_per_second

    # 添加随机波动 (±30%)
    variation = base_delay * random.uniform(-0.3, 0.3)

    # 限制在合理范围内
    delay = max(0.5, min(5.0, base_delay + variation))

    return delay
```

### 消息间固定延迟

```python
# 简单方案：固定随机延迟
async def send_with_delay(messages: List[str]):
    for i, msg in enumerate(messages):
        if i > 0:
            await asyncio.sleep(random.uniform(1.5, 3.5))
        await send_message(msg)
```

---

## 注意事项

1. **消息顺序**：确保多条消息按顺序发送，不能并行
2. **发送失败处理**：中途失败是否继续发送后续消息
3. **数据库存储**：每条消息单独存储，记录发送顺序
4. **UI 显示**：Sidecar 界面可能需要适配多消息预览
5. **AI 回复质量**：测试 AI 是否能合理使用分隔符
6. **分隔符冲突**：选择不太可能出现在内容中的分隔符

---

**创建时间**: 2026-01-21
**状态**: 待实施
**推荐方案**: 方案 A（分隔符拆分）
