# 批量消息发送架构设计方案 v4.0 (MVP极简版)

## 文档修订记录

| 版本     | 日期       | 修订内容                           | 作者        |
| -------- | ---------- | ---------------------------------- | ----------- |
| v1.0     | 2026-01-24 | 初始版本                           | Claude Code |
| v2.0     | 2026-01-24 | 新增 AI 大脑约束分析与多轮调用方案 | Claude Code |
| v3.0     | 2026-01-24 | 新增智能回复次数判定系统（复杂版） | Claude Code |
| **v4.0** | 2026-01-24 | **简化为MVP极简版（快速实现）**    | Claude Code |

---

## 一、现状分析与核心约束

### 1.1 当前消息发送机制

```
┌─────────────────────────────────────────────────────────────┐
│                    当前单条消息发送流程                        │
└─────────────────────────────────────────────────────────────┘
   Frontend/API         WeComService          ADBService         Android
        │                   │                    │                  │
        │  send_message()   │                    │                  │
        │──────────────────>│                    │                  │
        │                   │  get_ui_state()    │                  │
        │                   │───────────────────>│                  │
        │                   │  ui_tree, elements │                  │
        │                   │<───────────────────│                  │
        │                   │                    │                  │
        │                   │  tap(input_index)  │                  │
        │                   │───────────────────>│                  │
        │                   │                    │  tap at index    │
        │                   │                    │─────────────────>│
        │                   │                    │                  │
        │                   │  input_text(text)  │                  │
        │                   │───────────────────>│                  │
        │                   │                    │  input text      │
        │                   │                    │─────────────────>│
        │                   │                    │                  │
        │                   │  tap(send_button)  │                  │
        │                   │───────────────────>│                  │
        │                   │                    │  click send      │
        │                   │                    │─────────────────>│
        │                   │                    │                  │
        │  success: true    │                    │                  │
        │<──────────────────│                    │                  │
```

### 1.2 当前 AI 调用机制（关键约束）

#### AI 大脑请求格式

```json
{
  "chatInput": "用户消息或提示词",
  "sessionId": "sync_ABC123_1703318400000",
  "username": "sync_ABC123",
  "message_type": "text",
  "metadata": {
    "source": "followup_response_detector",
    "serial": "ABC123",
    "customer": "张三"
  }
}
```

#### AI 大脑响应格式

```json
{
  "output": "这是AI生成的单条回复消息",
  "session_id": "xxx",
  "success": true
}
```

#### ⚠️ **核心约束**

| 约束项         | 描述                                           | 影响                   |
| -------------- | ---------------------------------------------- | ---------------------- |
| **单条输出**   | AI 大脑一次请求只返回一条消息（`output` 字段） | 无法单次获得批量消息   |
| **有状态会话** | 通过 `sessionId` 保持上下文连续性              | 可复用会话生成连贯消息 |
| **无批量接口** | AI 大脑不提供批量生成 API                      | 需要客户端多次调用     |
| **网络延迟**   | 每次 AI 调用耗时 1-3 秒                        | 批量生成需要累积延迟   |

### 1.3 当前限制汇总

| 限制点       | 描述                                | 影响                 |
| ------------ | ----------------------------------- | -------------------- |
| 单条发送     | `send_message()` 每次只处理一条文本 | 无法一次发送多条消息 |
| 单条 AI 生成 | AI 大脑一次请求只返回一条消息       | 批量生成需要多次调用 |
| 串行处理     | 消息队列逐条执行                    | 多条消息耗时累加     |
| UI刷新频繁   | 每条消息都刷新UI状态                | 性能开销大           |

---

## 二、AI 批量消息生成方案设计

### 2.1 核心挑战

要实现批量消息发送，需要解决两个独立问题：

1. **批量生成**：如何从 AI 大脑获取多条消息？（AI 层面）
2. **批量发送**：如何高效发送多条消息？（发送层面）

```
┌─────────────────────────────────────────────────────────────┐
│                   批量消息发送的两层问题                      │
└─────────────────────────────────────────────────────────────┘

用户需求: "给新用户发一组欢迎消息"
         │
         ▼
┌────────────────┐
│  问题1: AI生成  │  ← AI 大脑约束：一次只能生成一条
│  如何获得3-5条  │     需要多次调用 + 会话复用
│  连贯的消息?    │
└────────────────┘
         │
         ▼ ["消息1", "消息2", "消息3"]
┌────────────────┐
│  问题2: 消息发送 │  ← ADB 约束：每次都需要UI操作
│  如何高效发送?  │     需要流水线优化
└────────────────┘
         │
         ▼
    企业微信发送
```

### 2.2 AI 批量生成方案对比

| 方案                      | 策略                         | 优点                 | 缺点                   | 推荐度     |
| ------------------------- | ---------------------------- | -------------------- | ---------------------- | ---------- |
| **方案1: 会话链式生成**   | 同一 sessionId，顺序多次调用 | 上下文连贯，实现简单 | 耗时较长               | ⭐⭐⭐⭐⭐ |
| **方案2: 并发独立调用**   | 多个 sessionId，并发调用     | 速度快               | 上下文独立，可能不连贯 | ⭐⭐⭐     |
| **方案3: 模板 + AI 填充** | 预定义结构，AI 填充内容      | 减少调用次数         | 灵活性低               | ⭐⭐       |
| **方案4: 后端代理批量**   | 后端循环调用，对上层透明     | 调用方无感知         | 后端复杂度高           | ⭐⭐⭐⭐   |

---

### 2.3 方案 1: 会话链式生成（推荐⭐⭐⭐⭐⭐）

#### 核心思路

利用 AI 大脑的 **sessionId 会话机制**，在同一个会话中多次请求，AI 会记住上下文并生成连贯的消息序列。

#### 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│              AI 会话链式批量生成流程                          │
└─────────────────────────────────────────────────────────────┘

用户请求: "为新用户生成3条欢迎消息"
         │
         ▼
生成统一 sessionId: "batch_welcome_{timestamp}"
         │
         ├── AI 请求 #1 (使用同一 sessionId)
         │   Prompt: "你是客服，请生成新用户欢迎语的第1条消息"
         │   Context: (空，首次请求)
         │   → AI 返回: "您好！欢迎添加我们的企业微信～"
         │
         ├── AI 请求 #2 (使用同一 sessionId)
         │   Prompt: "基于上一条，生成第2条消息（公司介绍）"
         │   Context: AI 记住了上一条是"欢迎语"
         │   → AI 返回: "我们是XX公司，专注于XX领域..."
         │
         └── AI 请求 #3 (使用同一 sessionId)
             Prompt: "基于前两条，生成第3条消息（引导语）"
             Context: AI 记住了"欢迎语"和"公司介绍"
             → AI 返回: "有任何问题随时联系我～"

结果: ["您好！欢迎...", "我们是XX公司...", "有任何问题..."]
      ↑        上下文连贯，逻辑递进
```

#### 代码实现

**新增文件**：`src/wecom_automation/servic../03-impl-and-arch/key-modules/batch_generator.py`

```python
"""
AI 批量消息生成器 - 会话链式方案

利用 AI 大脑的 sessionId 会话机制，实现上下文连贯的批量消息生成。
"""
import asyncio
import logging
import aiohttp
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import uuid
from datetime import datetime

class BatchIntent(Enum):
    """批量消息意图类型"""
    WELCOME_NEW_USER = "welcome_new_user"        # 欢迎新用户
    PRODUCT_INTRO = "product_intro"              # 产品介绍
    FAQ_REPLY = "faq_reply"                      # FAQ 回复
    PROMOTION = "promotion"                      # 促销推广
    FOLLOW_UP = "follow_up"                      # 跟进消息

@dataclass
class BatchGenerateRequest:
    """批量生成请求"""
    intent: BatchIntent                          # 意图类型
    customer_name: Optional[str] = None          # 客户名称
    customer_context: Optional[str] = None       # 客户上下文
    message_count: int = 3                       # 生成消息数量
    custom_prompt: Optional[str] = None          # 自定义提示词

@dataclass
class BatchGenerateResult:
    """批量生成结果"""
    success: bool
    messages: List[str]
    session_id: str
    total_time: float
    errors: List[str]

class AIBatchGenerator:
    """AI 批量消息生成器"""

    def __init__(
        self,
        ai_server_url: str,
        ai_timeout: int = 15,
        logger: Optional[logging.Logger] = None,
    ):
        """
        初始化 AI 批量生成器

        Args:
            ai_server_url: AI 大脑服务地址
            ai_timeout: AI 请求超时时间（秒）
            logger: 日志记录器
        """
        self.ai_server_url = ai_server_url.rstrip('/')
        self.ai_timeout = ai_timeout
        self.logger = logger or logging.getLogger(__name__)

        # 确保以 /chat 结尾
        if not self.ai_server_url.endswith('/chat'):
            self.ai_server_url += '/chat'

    async def generate_batch(
        self,
        request: BatchGenerateRequest,
        on_progress: Optional[callable] = None,
    ) -> BatchGenerateResult:
        """
        使用会话链式方式批量生成消息

        Args:
            request: 批量生成请求
            on_progress: 进度回调 (index, message)

        Returns:
            BatchGenerateResult: 生成结果
        """
        start_time = asyncio.get_event_loop().time()

        # 生成统一的 sessionId（确保所有请求在同一个会话中）
        session_id = f"batch_{request.intent.value}_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}"

        messages = []
        errors = []

        self.logger.info(
            f"Starting batch generation: intent={request.intent.value}, "
            f"count={request.message_count}, session={session_id}"
        )

        # 构建上下文提示（第一条消息的上下文）
        base_context = self._build_base_context(request)

        for idx in range(request.message_count):
            try:
                # 构建第 idx+1 条消息的提示词
                prompt = self._build_prompt_for_index(
                    request=request,
                    index=idx,
                    previous_messages=messages,
                )

                self.logger.debug(
                    f"[{idx+1}/{request.message_count}] Sending AI request "
                    f"(session={session_id})"
                )

                # 调用 AI 大脑
                message = await self._call_ai_brain(
                    prompt=prompt,
                    session_id=session_id,
                    customer_name=request.customer_name,
                )

                if message:
                    messages.append(message)
                    self.logger.info(
                        f"[{idx+1}/{request.message_count}] ✅ Generated: "
                        f"{message[:30]}..."
                    )

                    # 进度回调
                    if on_progress:
                        await on_progress(idx, message)
                else:
                    error_msg = f"Message {idx+1} generation failed"
                    errors.append(error_msg)
                    self.logger.warning(f"[{idx+1}/{request.message_count}] ❌ {error_msg}")

                    # 遇到失败是否继续？
                    # 策略：继续尝试生成剩余消息，而不是直接失败

                # 避免请求过快
                if idx < request.message_count - 1:
                    await asyncio.sleep(0.5)

            except Exception as e:
                error_msg = f"Message {idx+1} error: {str(e)}"
                errors.append(error_msg)
                self.logger.error(f"[{idx+1}/{request.message_count}] ❌ {e}")

        total_time = asyncio.get_event_loop().time() - start_time

        return BatchGenerateResult(
            success=len(messages) > 0,
            messages=messages,
            session_id=session_id,
            total_time=total_time,
            errors=errors,
        )

    def _build_base_context(self, request: BatchGenerateRequest) -> str:
        """构建基础上下文"""
        context_parts = []

        if request.customer_name:
            context_parts.append(f"客户姓名: {request.customer_name}")

        if request.customer_context:
            context_parts.append(f"客户背景: {request.customer_context}")

        if request.intent == BatchIntent.WELCOME_NEW_USER:
            context_parts.append("场景: 新用户首次添加企业微信")
        elif request.intent == BatchIntent.PRODUCT_INTRO:
            context_parts.append("场景: 产品介绍")
        elif request.intent == BatchIntent.FAQ_REPLY:
            context_parts.append("场景: 常见问题回复")
        elif request.intent == BatchIntent.PROMOTION:
            context_parts.append("场景: 促销活动推广")
        elif request.intent == BatchIntent.FOLLOW_UP:
            context_parts.append("场景: 客户跟进")

        return "\n".join(context_parts)

    def _build_prompt_for_index(
        self,
        request: BatchGenerateRequest,
        index: int,
        previous_messages: List[str],
    ) -> str:
        """
        为指定索引的消息构建提示词

        关键：利用会话上下文，让 AI 知道这是第几条、前面的内容是什么
        """
        # 意图特定的提示词模板
        intent_prompts = {
            BatchIntent.WELCOME_NEW_USER: [
                "生成新用户欢迎语的第1条消息（简洁的问候）",
                "基于上一条欢迎语，生成第2条消息（公司简介）",
                "基于前面的内容，生成第3条消息（核心优势介绍）",
                "基于前面的内容，生成第4条消息（引导语或联系方式）",
            ],
            BatchIntent.PRODUCT_INTRO: [
                "生成产品介绍的第1条消息（产品概述）",
                "基于上一条，生成第2条消息（核心功能）",
                "基于前面的内容，生成第3条消息（使用场景）",
            ],
            BatchIntent.FAQ_REPLY: [
                "生成FAQ回复的第1条消息（直接回答问题）",
                "基于上一条，生成第2条消息（补充说明）",
                "基于前面的内容，生成第3条消息（引导进一步咨询）",
            ],
            BatchIntent.PROMOTION: [
                "生成促销活动的第1条消息（活动吸引点）",
                "基于上一条，生成第2条消息（具体优惠内容）",
                "基于前面的内容，生成第3条消息（紧迫感营造）",
            ],
            BatchIntent.FOLLOW_UP: [
                "生成跟进消息的第1条消息（询问近况）",
                "基于上一条，生成第2条消息（提供价值）",
                "基于前面的内容，生成第3条消息（行动召唤）",
            ],
        }

        # 使用预定义模板（如果存在）
        if request.intent in intent_prompts:
            templates = intent_prompts[request.intent]
            if index < len(templates):
                base_prompt = templates[index]
            else:
                base_prompt = f"基于前面的内容，生成第{index+1}条消息（继续对话）"
        else:
            base_prompt = f"生成第{index+1}条消息"

        # 添加自定义提示词（如果有）
        if request.custom_prompt and index == 0:
            base_prompt = f"{request.custom_prompt}\n\n{base_prompt}"

        return base_prompt

    async def _call_ai_brain(
        self,
        prompt: str,
        session_id: str,
        customer_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        调用 AI 大脑生成单条消息

        Args:
            prompt: 提示词
            session_id: 会话ID（关键：复用同一会话）
            customer_name: 客户名称（用于 metadata）

        Returns:
            生成的消息文本，失败返回 None
        """
        payload = {
            "chatInput": prompt,
            "sessionId": session_id,
            "username": f"batch_generator_{session_id}",
            "message_type": "text",
            "metadata": {
                "source": "ai_batch_generator",
                "customer": customer_name or "unknown",
                "batch_mode": True,
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.ai_server_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.ai_timeout)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        message = data.get("output", "").strip()

                        if message:
                            return message
                        else:
                            self.logger.warning(f"AI returned empty message")
                            return None
                    else:
                        text = await response.text()
                        self.logger.error(f"AI returned {response.status}: {text}")
                        return None

        except asyncio.TimeoutError:
            self.logger.error(f"AI request timeout after {self.ai_timeout}s")
            return None
        except Exception as e:
            self.logger.error(f"AI request error: {e}")
            return None

    async def generate_and_send_batch(
        self,
        request: BatchGenerateRequest,
        wecom_service,
        on_generate_progress: Optional[callable] = None,
        on_send_progress: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        生成并发送批量消息（一站式服务）

        Args:
            request: 批量生成请求
            wecom_service: WeComService 实例
            on_generate_progress: 生成进度回调
            on_send_progress: 发送进度回调

        Returns:
            完整的生成+发送结果
        """
        # 阶段1: 生成消息
        self.logger.info("Phase 1: Generating batch messages...")
        gen_result = await self.generate_batch(request, on_progress=on_generate_progress)

        if not gen_result.success or not gen_result.messages:
            return {
                "success": False,
                "error": "Failed to generate messages",
                "gen_result": gen_result,
            }

        self.logger.info(f"Phase 1 complete: {len(gen_result.messages)} messages generated")

        # 阶段2: 发送消息（使用流水线优化）
        self.logger.info("Phase 2: Sending batch messages...")

        from wecom_automation.services.pipeline_sender import PipelineSender
        pipeline = PipelineSender(wecom_service, logger=self.logger)

        send_result = await pipeline.send_batch(
            gen_result.messages,
            on_progress=on_send_progress,
        )

        self.logger.info(f"Phase 2 complete: {send_result['success']}/{send_result['total']} sent")

        return {
            "success": send_result['failed'] == 0,
            "generation": {
                "total": request.message_count,
                "generated": len(gen_result.messages),
                "time": gen_result.total_time,
            },
            "sending": {
                "total": send_result['total'],
                "success": send_result['success'],
                "failed": send_result['failed'],
                "time": send_result['total_time'],
            },
            "total_time": gen_result.total_time + send_result['total_time'],
            "messages": gen_result.messages,
        }
```

#### 使用示例

```python
# 示例1: 欢迎新用户
generator = AIBatchGenerator(
    ai_server_url="http://47.113.187.234:8000",
    ai_timeout=15,
)

request = BatchGenerateRequest(
    intent=BatchIntent.WELCOME_NEW_USER,
    customer_name="张三",
    message_count=4,
)

result = await generator.generate_batch(
    request,
    on_progress=lambda idx, msg: print(f"{idx+1}: {msg}")
)

print(result.messages)
# 输出:
# [
#   "您好！欢迎添加我们的企业微信～",
#   "我们是XX公司，专注于企业数字化解决方案",
#   "我们的核心产品包括CRM、ERP等系统",
#   "有任何问题随时联系我～"
# ]

# 示例2: 一站式生成并发送
result = await generator.generate_and_send_batch(
    request=request,
    wecom_service=wecom,
)
print(f"Generated {result['generation']['generated']} messages")
print(f"Sent {result['sending']['success']} messages")
print(f"Total time: {result['total_time']:.2f}s")
```

#### 优缺点

| 优点                         | 缺点                                |
| ---------------------------- | ----------------------------------- |
| ✅ 上下文连贯（AI 记住前文） | ❌ 耗时较长（N 条消息 = N 次调用）  |
| ✅ 实现简单，复用现有 AI     | ❌ 依赖 sessionId 机制              |
| ✅ 无需修改 AI 大脑          | ❌ 单点失败风险（某条失败影响后续） |
| ✅ 灵活性高，支持各种意图    |                                     |

---

### 2.4 方案 2: 并发独立调用

#### 核心思路

使用多个独立的 `sessionId`，并发调用 AI 大脑，同时生成多条消息。

#### 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│              AI 并发独立批量生成流程                          │
└─────────────────────────────────────────────────────────────┘

用户请求: "生成3条欢迎消息"
         │
         ▼
    创建3个独立 sessionId
         │
    ┌────┴────┬────────┬────────┐
    ▼         ▼        ▼        ▼
 AI 请求#1  AI 请求#2  AI 请求#3  (并发执行)
 session_1  session_2  session_3
    │         │        │
    ▼         ▼        ▼
 "您好！"  "欢迎添加"  "有什么..."
    │         │        │
    └────┬────┴────────┴────────┘
         │
         ▼
    收集结果
 ["您好！", "欢迎添加", "有什么..."]
      ↑
      问题: 消息之间可能不连贯（各自独立生成）
```

#### 代码实现

```python
class AIConcurrentBatchGenerator:
    """AI 并发批量生成器"""

    async def generate_batch_concurrent(
        self,
        request: BatchGenerateRequest,
        on_progress: Optional[callable] = None,
    ) -> BatchGenerateResult:
        """
        并发生成多条消息（独立会话）

        优点：速度快
        缺点：上下文不连贯
        """
        start_time = asyncio.get_event_loop().time()

        # 为每条消息创建独立的任务
        tasks = []
        for idx in range(request.message_count):
            # 每条消息使用独立的 sessionId
            session_id = f"batch_concurrent_{uuid.uuid4().hex[:8]}_{idx}_{int(datetime.now().timestamp())}"

            task = self._generate_single_message(
                prompt=self._build_standalone_prompt(request, idx),
                session_id=session_id,
                index=idx,
            )
            tasks.append(task)

        # 并发执行所有任务
        self.logger.info(f"Launching {len(tasks)} concurrent AI requests...")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        messages = []
        errors = []

        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append(f"Message {idx+1}: {str(result)}")
            elif result:
                messages.append(result)
                if on_progress:
                    await on_progress(idx, result)
            else:
                errors.append(f"Message {idx+1}: Generation failed")

        total_time = asyncio.get_event_loop().time() - start_time

        return BatchGenerateResult(
            success=len(messages) > 0,
            messages=messages,
            session_id="concurrent",
            total_time=total_time,
            errors=errors,
        )

    async def _generate_single_message(
        self,
        prompt: str,
        session_id: str,
        index: int,
    ) -> Optional[str]:
        """生成单条消息（独立会话）"""
        payload = {
            "chatInput": prompt,
            "sessionId": session_id,
            "username": f"concurrent_{session_id}",
            "message_type": "text",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.ai_server_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.ai_timeout)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("output", "").strip()
                return None

    def _build_standalone_prompt(
        self,
        request: BatchGenerateRequest,
        index: int,
    ) -> str:
        """构建独立提示词（不依赖前文）"""
        base_prompts = {
            BatchIntent.WELCOME_NEW_USER: [
                "生成一条简洁的新用户欢迎语",
                "生成一条公司简介消息",
                "生成一条产品核心优势介绍",
                "生成一条引导客户咨询的消息",
            ],
            # ... 其他意图
        }

        prompts = base_prompts.get(request.intent, [f"生成第{i+1}条消息" for i in range(request.message_count)])

        if index < len(prompts):
            return prompts[index]
        return f"生成第{index+1}条消息"
```

#### 优缺点

| 优点                  | 缺点                      |
| --------------------- | ------------------------- |
| ✅ 速度快（并发执行） | ❌ 上下文不连贯           |
| ✅ 单条失败不影响其他 | ❌ 消息可能缺乏逻辑关联   |
| ✅ 总耗时接近单条耗时 | ❌ 无法利用 AI 的记忆能力 |

---

### 2.5 方案 3: 后端代理批量（推荐用于前端调用）

#### 核心思路

后端提供统一的批量生成 API，内部封装 AI 多轮调用逻辑，对前端透明。

#### API 设计

```python
# wecom-desktop/backend/routers/ai_batch.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class BatchGenerateRequest(BaseModel):
    """批量生成请求"""
    intent: str                     # "welcome_new_user" | "product_intro" | ...
    customerName: Optional[str] = None
    customerContext: Optional[str] = None
    messageCount: int = 3
    customPrompt: Optional[str] = None

class BatchGenerateResponse(BaseModel):
    """批量生成响应"""
    success: bool
    messages: List[str]
    totalTime: float
    errors: List[str]

@router.post../03-impl-and-arch/key-modules/batch-generate")
async def batch_generate_messages(
    request: BatchGenerateRequest,
):
    """
    批量生成 AI 消息（后端代理）

    内部使用会话链式调用 AI 大脑，对前端透明。

    Request:
    {
        "intent": "welcome_new_user",
        "customerName": "张三",
        "messageCount": 4
    }

    Response:
    {
        "success": true,
        "messages": [
            "您好！欢迎添加...",
            "我们是XX公司...",
            "核心产品包括...",
            "有任何问题..."
        ],
        "totalTime": 8.5,
        "errors": []
    }
    """
    from wecom_automation.services.ai.batch_generator import (
        AIBatchGenerator,
        BatchIntent,
        BatchGenerateRequest as AIRequest,
    )
    from services.settings import get_settings_service

    # 获取 AI 配置
    settings = get_settings_service()
    global_settings = settings.get_flat_settings()
    ai_server_url = global_settings.get('aiServerUrl', 'http://localhost:8000')
    ai_timeout = global_settings.get('aiReplyTimeout', 15)

    # 构建请求
    intent_map = {
        "welcome_new_user": BatchIntent.WELCOME_NEW_USER,
        "product_intro": BatchIntent.PRODUCT_INTRO,
        "faq_reply": BatchIntent.FAQ_REPLY,
        "promotion": BatchIntent.PROMOTION,
        "follow_up": BatchIntent.FOLLOW_UP,
    }

    batch_intent = intent_map.get(request.intent)
    if not batch_intent:
        raise HTTPException(status_code=400, detail=f"Unknown intent: {request.intent}")

    ai_request = AIRequest(
        intent=batch_intent,
        customer_name=request.customerName,
        customer_context=request.customerContext,
        message_count=request.messageCount,
        custom_prompt=request.customPrompt,
    )

    # 创建生成器
    generator = AIBatchGenerator(
        ai_server_url=ai_server_url,
        ai_timeout=ai_timeout,
    )

    # 生成消息
    result = await generator.generate_batch(ai_request)

    return BatchGenerateResponse(
        success=result.success,
        messages=result.messages,
        totalTime=result.total_time,
        errors=result.errors,
    )
```

#### 前端调用示例

```typescript
// wecom-desktop/src/services/aiService.ts

export interface BatchGenerateRequest {
  intent: 'welcome_new_user' | 'product_intro' | 'faq_reply'
  customerName?: string
  customerContext?: string
  messageCount?: number
  customPrompt?: string
}

export async function generateBatchMessages(
  request: BatchGenerateRequest
): Promise<BatchGenerateResponse> {
  const response = await fetch(
    'http://localhost:87../03-impl-and-arch/key-modules/batch-generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  )

  return response.json()
}

// 使用示例
const result = await generateBatchMessages({
  intent: 'welcome_new_user',
  customerName: '张三',
  messageCount: 4,
})

console.log(result.messages)
// ["您好！欢迎添加...", "我们是XX公司...", ...]
```

#### 优缺点

| 优点                | 缺点                |
| ------------------- | ------------------- |
| ✅ 对前端透明       | ❌ 后端复杂度增加   |
| ✅ 统一管理 AI 调用 | ❌ 需要新增后端接口 |
| ✅ 易于监控和日志   |                     |

---

## 三、发送层面：流水线优化方案

在获得批量消息后，需要高效发送。详见 **第四章：流水线发送器**。

---

## 四、你可能没想到的问题（架构设计补充）

### 4.1 消息连贯性保证

#### 问题

批量生成的消息是否需要逻辑连贯？

- **场景A（欢迎语）**：需要连贯

  ```
  "您好！欢迎添加～" → "我们是XX公司" → "核心产品是..."
  ```

- **场景B（并发独立）**：不需要连贯
  ```
  多个独立的FAQ回复
  ```

#### 解决方案

```python
class MessageCoherenceChecker:
    """消息连贯性检查器"""

    def check_coherence(self, messages: List[str]) -> Dict[str, Any]:
        """
        检查消息列表的连贯性

        检查项：
        1. 长度分布（避免某条过长或过短）
        2. 主题一致性（通过关键词检测）
        3. 逻辑递进（是否有"首先"、"其次"、"最后"等词）
        """
        stats = {
            "lengths": [len(msg) for msg in messages],
            "avg_length": sum(len(msg) for msg in messages) / len(messages),
            "max_length_ratio": max(len(msg) for msg in messages) / min(len(msg) for msg in messages) if messages else 0,
            "has_progression": self._check_progression_keywords(messages),
        }

        # 评估连贯性分数（0-100）
        score = 100
        if stats["max_length_ratio"] > 5:  # 某条消息过长
            score -= 20
        if not stats["has_progression"]:
            score -= 10

        return {
            "score": score,
            "stats": stats,
            "is_coherent": score >= 70,
        }

    def _check_progression_keywords(self, messages: List[str]) -> bool:
        """检查是否有递进关键词"""
        progression_words = ["首先", "其次", "另外", "此外", "最后", "综上"]
        combined = "".join(messages)
        return any(word in combined for word in progression_words)
```

### 4.2 发送顺序保证

#### 问题

批量消息发送时，如何确保顺序正确？

#### 风险场景

```
期望顺序: Msg1 → Msg2 → Msg3
实际顺序: Msg2 → Msg1 → Msg3 (由于并发或网络延迟)
```

#### 解决方案

```python
class OrderedBatchSender:
    """有序批量发送器"""

    async def send_batch_ordered(
        self,
        messages: List[str],
        wecom_service,
    ) -> Dict[str, Any]:
        """
        严格按顺序发送批量消息

        关键：使用 asyncio.wait() 确保串行执行
        """
        results = []

        for idx, message in enumerate(messages):
            # 发送当前消息
            success, actual = await wecom_service.send_message(message)

            results.append({
                "index": idx,
                "message": message,
                "success": success,
            })

            # 等待发送完成（确保出现在聊天记录中）
            if success:
                await self._wait_for_message_appear(wecom_service, actual or message)

            # 延迟（防止过快）
            if idx < len(messages) - 1:
                await asyncio.sleep(1.5)

        return {
            "total": len(messages),
            "success": sum(1 for r in results if r["success"]),
            "results": results,
        }

    async def _wait_for_message_appear(
        self,
        wecom_service,
        message: str,
        timeout: float = 3.0,
    ) -> bool:
        """等待消息出现在聊天记录中"""
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            tree = await wecom_service.adb.get_ui_tree()
            messages = wecom_service.ui_parser.extract_conversation_messages(tree)

            # 检查最近3条消息
            for msg in reversed(messages[-3:]):
                if getattr(msg, 'is_self', False) and message in (getattr(msg, 'content') or ''):
                    return True

            await asyncio.sleep(0.3)

        return False
```

### 4.3 发送失败回滚机制

#### 问题

批量发送 5 条消息，第 3 条失败怎么办？

```
Msg1 ✅ 已发送
Msg2 ✅ 已发送
Msg3 ❌ 失败
Msg4 🤷 还没发
Msg5 🤷 还没发
```

#### 解决方案选项

| 策略         | 描述                | 适用场景     |
| ------------ | ------------------- | ------------ |
| **全部重试** | 撤回前2条，重发全部 | 重要消息     |
| **继续发送** | 跳过第3条，继续发送 | 非关键消息   |
| **停止发送** | 遇到失败立即停止    | 需要严格顺序 |

```python
@dataclass
class FailureHandlingStrategy:
    """失败处理策略"""
    on_failure: str = "continue"  # "continue" | "stop" | "retry_all"
    max_retries: int = 1
    retry_delay: float = 2.0

class ResilientBatchSender:
    """弹性批量发送器"""

    async def send_batch_with_failure_handling(
        self,
        messages: List[str],
        wecom_service,
        strategy: FailureHandlingStrategy,
    ) -> Dict[str, Any]:
        """
        带失败处理的批量发送

        根据策略决定失败后的行为
        """
        if strategy.on_failure == "continue":
            return await self._send_continue_on_failure(messages, wecom_service)
        elif strategy.on_failure == "stop":
            return await self._send_stop_on_failure(messages, wecom_service)
        elif strategy.on_failure == "retry_all":
            return await self._send_retry_all(messages, wecom_service, strategy)

    async def _send_continue_on_failure(
        self,
        messages: List[str],
        wecom_service,
    ) -> Dict[str, Any]:
        """遇到失败继续发送"""
        results = []

        for idx, message in enumerate(messages):
            try:
                success, _ = await wecom_service.send_message(message)
                results.append({"index": idx, "success": success})
            except Exception as e:
                results.append({"index": idx, "success": False, "error": str(e)})
                # 继续发送剩余消息

        return {"results": results, "strategy": "continue_on_failure"}
```

### 4.4 用户感知优化

#### 问题

批量发送多条消息时，用户会看到多条消息"同时"到达，体验不佳。

#### 解决方案

```
方案1: 模拟真实对话节奏
  Msg1 → 延迟2s → Msg2 → 延迟3s → Msg3

方案2: 显示"对方正在输入..."提示
  （需要企业微信支持，目前可能无法实现）

方案3: 分批发送
  先发2条 → 等待用户回复 → 再发剩余2条
```

```python
class HumanLikeBatchSender:
    """模拟人类发送节奏的批量发送器"""

    # 人类打字速度：约 5-10 字/秒
    TYPING_SPEED_CHARS_PER_SECOND = 7

    async def send_batch_human_like(
        self,
        messages: List[str],
        wecom_service,
    ) -> Dict[str, Any]:
        """
        模拟人类发送节奏

        根据消息长度计算打字时间，添加随机延迟
        """
        import random

        results = []

        for idx, message in enumerate(messages):
            # 发送消息
            success, _ = await wecom_service.send_message(message)
            results.append({"index": idx, "success": success})

            # 计算人类打这条消息需要的时间
            typing_time = len(message) / self.TYPING_SPEED_CHARS_PER_SECOND

            # 添加随机变动（±20%）
            typing_time *= random.uniform(0.8, 1.2)

            # 最小间隔1秒，最大间隔5秒
            delay = max(1.0, min(typing_time, 5.0))

            # 最后一条不需要延迟
            if idx < len(messages) - 1:
                await asyncio.sleep(delay)

        return {"results": results}
```

### 4.5 消息审核机制

#### 问题

AI 生成的批量消息是否需要人工审核？

#### 风险

- AI 生成不当内容（敏感词、错误信息）
- 与客户实际情况不符

#### 解决方案

```python
class BatchMessageModerator:
    """批量消息审核器"""

    async def moderate_messages(
        self,
        messages: List[str],
    ) -> Dict[str, Any]:
        """
        审核批量消息

        检查项：
        1. 敏感词过滤
        2. 长度检查（避免过长）
        3. 重复内容检测
        4. 格式验证
        """
        issues = []

        for idx, message in enumerate(messages):
            # 敏感词检查
            if self._contains_sensitive_words(message):
                issues.append({
                    "index": idx,
                    "type": "sensitive_content",
                    "message": message,
                })

            # 长度检查
            if len(message) > 500:
                issues.append({
                    "index": idx,
                    "type": "too_long",
                    "length": len(message),
                })

            # 重复检测
            for prev_idx, prev_msg in enumerate(messages[:idx]):
                if self._similarity(message, prev_msg) > 0.9:
                    issues.append({
                        "index": idx,
                        "type": "duplicate",
                        "duplicate_of": prev_idx,
                    })
                    break

        return {
            "passed": len(issues) == 0,
            "issues": issues,
        }

    def _contains_sensitive_words(self, message: str) -> bool:
        """敏感词检测（示例）"""
        sensitive_words = ["违禁词1", "违禁词2"]
        return any(word in message for word in sensitive_words)

    def _similarity(self, msg1: str, msg2: str) -> float:
        """简单相似度计算"""
        # 实际应用中应使用更复杂的算法（如编辑距离、余弦相似度）
        return 1.0 if msg1 == msg2 else 0.0
```

### 4.6 跨设备一致性

#### 问题

多设备同时给同一客户发送批量消息，可能造成冲突。

#### 解决方案

```python
class DistributedBatchSendLock:
    """分布式批量发送锁"""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def acquire_lock(
        self,
        customer_name: str,
        channel: Optional[str],
        device_serial: str,
        ttl: int = 60,
    ) -> bool:
        """
        获取批量发送锁

        确保同一客户在同一时间只被一个设备处理
        """
        lock_key = f"batch_send_lock:{customer_name}:{channel or 'default'}"

        # 尝试设置锁
        acquired = await self.redis.set(
            lock_key,
            device_serial,
            nx=True,  # 仅当 key 不存在时设置
            ex=ttl,   # 过期时间
        )

        return acquired

    async def release_lock(
        self,
        customer_name: str,
        channel: Optional[str],
    ):
        """释放锁"""
        lock_key = f"batch_send_lock:{customer_name}:{channel or 'default'}"
        await self.redis.delete(lock_key)
```

### 4.7 会话上下文隔离

#### 问题

同一设备同时处理多个客户，AI 的 `sessionId` 是否会混淆？

#### 风险场景

```
设备A正在处理客户X和客户Y：
- 客户X的批量生成使用 session_1
- 客户Y的批量生成使用 session_2

如果 AI 服务未正确隔离，可能造成上下文污染
```

#### 解决方案

```python
class SessionIdGenerator:
    """会话ID生成器（确保隔离）"""

    @staticmethod
    def generate_batch_session_id(
        device_serial: str,
        customer_name: str,
        intent: str,
    ) -> str:
        """
        生成唯一的批量会话ID

        格式: batch_{device}_{customer}_{intent}_{timestamp}
        """
        import hashlib
        import uuid

        # 客户名称哈希（避免特殊字符）
        customer_hash = hashlib.md5(customer_name.encode()).hexdigest()[:8]

        # 时间戳
        timestamp = int(datetime.now().timestamp())

        # 唯一标识
        unique_id = uuid.uuid4().hex[:8]

        return f"batch_{device_serial}_{customer_hash}_{intent}_{timestamp}_{unique_id}"
```

---

## 五、完整方案推荐与实施路径

### 5.1 最终推荐方案

基于以上分析，推荐采用 **混合方案**：

| 场景         | AI 生成方案  | 发送方案     |
| ------------ | ------------ | ------------ |
| **通用场景** | 会话链式生成 | 流水线发送   |
| **独立消息** | 并发独立生成 | 串行发送     |
| **前端调用** | 后端代理批量 | 后端代理批量 |

### 5.2 架构分层设计

```
┌─────────────────────────────────────────────────────────────┐
│                    批量消息发送完整架构                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                        前端层                                │
│  - 批量发送 UI 组件                                           │
│  - 消息预览与编辑                                             │
│  - 进度监控                                                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      后端 API 层                              │
│  POS../03-impl-and-arch/key-modules/batch-generate         ← 生成批量消息              │
│  POS../03-impl-and-arch/{serial}/send-batch ← 发送批量消息            │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
┌──────────────────────┐      ┌──────────────────────┐
│    AI 生成层         │      │    发送层            │
│  ┌────────────────┐  │      │  ┌────────────────┐ │
│  │ 会话链式生成   │  │      │  │ 流水线发送器   │ │
│  │ (连贯消息)     │  │      │  │ (高性能)       │ │
│  └────────────────┘  │      │  └────────────────┘ │
│  ┌────────────────┐  │      │  ┌────────────────┐ │
│  │ 并发独立生成   │  │      │  │ 有序发送器     │ │
│  │ (独立消息)     │  │      │  │ (严格顺序)     │ │
│  └────────────────┘  │      │  └────────────────┘ │
│  ┌────────────────┐  │      │  ┌────────────────┐ │
│  │ 消息审核器     │  │      │  │ 弹性发送器     │ │
│  │ (内容过滤)     │  │      │  │ (失败处理)     │ │
│  └────────────────┘  │      │  └────────────────┘ │
└──────────────────────┘      └──────────────────────┘
            │                               │
            └───────────────┬───────────────┘
                            ▼
                    ┌───────────────┐
                    │  AI 大脑服务   │
                    │ (单条输出)     │
                    └───────────────┘
```

### 5.3 实施路径

#### 阶段 1: AI 批量生成（2-3天）

1. 实现 `AIBatchGenerator`（会话链式）
2. 实现后端 API../03-impl-and-arch/key-modules/batch-generate`
3. 添加单元测试
4. 验证消息连贯性

#### 阶段 2: 流水线发送（2-3天）

1. 实现 `PipelineSender`
2. 实现有序发送器
3. 性能基准测试
4. 添加失败处理

#### 阶段 3: 安全与审核（1-2天）

1. 实现消息审核器
2. 实现分布式锁
3. 添加敏感词过滤
4. 添加监控告警

#### 阶段 4: 前端集成（2天）

1. 实现批量发送 UI
2. 添加消息预览
3. 添加进度监控
4. 添加编辑功能

#### 阶段 5: 生产部署（1天）

1. 灰度发布
2. 监控验证
3. 性能调优
4. 文档完善

---

## 六、API 接口设计

### 6.1 AI 批量生成 API

```python
# POS../03-impl-and-arch/key-modules/batch-generate

{
  "intent": "welcome_new_user",      # 必填
  "customerName": "张三",             # 可选
  "customerContext": "新客户",        # 可选
  "messageCount": 4,                  # 默认3
  "customPrompt": "强调产品质量"       # 可选
}

# Response

{
  "success": true,
  "messages": [
    "您好！欢迎添加我们的企业微信～",
    "我们是XX公司，专注于...",
    "核心产品包括...",
    "有任何问题随时联系我～"
  ],
  "totalTime": 8.5,
  "errors": []
}
```

### 6.2 批量发送 API

```python
# POS../03-impl-and-arch/{serial}/send-batch

{
  "messages": ["消息1", "消息2", "消息3"],
  "strategy": "pipeline",              # "pipeline" | "ordered" | "resilient"
  "failureHandling": "continue",       # "continue" | "stop" | "retry_all"
  "humanLikeTiming": false,            # 是否模拟人类节奏
  "delayBetween": 1.5                  # 消息间隔（秒）
}

# Response

{
  "success": true,
  "total": 3,
  "sent": 3,
  "failed": 0,
  "totalTime": 8.2,
  "results": [
    {"index": 0, "message": "消息1", "success": true},
    {"index": 1, "message": "消息2", "success": true},
    {"index": 2, "message": "消息3", "success": true}
  ]
}
```

---

## 七、风险与注意事项

### 7.1 技术风险

| 风险        | 影响         | 缓解措施           |
| ----------- | ------------ | ------------------ |
| AI 会话失效 | 消息不连贯   | 添加会话有效性检查 |
| 并发冲突    | 消息顺序错乱 | 使用分布式锁       |
| 发送失败    | 部分消息丢失 | 实现重试机制       |
| UI 状态变化 | 发送失败     | 状态检测与恢复     |

### 7.2 业务风险

| 风险        | 影响     | 缓解措施            |
| ----------- | -------- | ------------------- |
| AI 生成不当 | 客户投诉 | 消息审核 + 人工确认 |
| 频繁发送    | 账号限流 | 速率限制            |
| 用户体验差  | 取消关注 | 模拟人类节奏        |
| 跨设备冲突  | 重复发送 | 分布式锁            |

---

## 八、简化的批量回复决策系统（MVP版本）

### 8.1 核心设计原则

**极简MVP，聚焦核心**：

- ✅ 最多3条消息（简单固定策略）
- ✅ AI会话链式生成（保证连贯性）
- ✅ 质量检查（保证准确性）
- ❌ 删除复杂决策逻辑
- ❌ 删除疲劳度管理
- ❌ 删除A/B测试
- ❌ 删除实时终止

### 8.2 极简决策策略

```
┌─────────────────────────────────────────────────────────────┐
│                   MVP批量回复决策流程                         │
└─────────────────────────────────────────────────────────────┘

用户触发批量回复
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  步骤1: 随机决定条数                                        │
│  • 70%概率: 3条                                             │
│  • 20%概率: 2条                                             │
│  • 10%概率: 1条                                             │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  步骤2: AI会话链式生成（保证连贯性）                        │
│  • 使用统一的sessionId                                      │
│  • 按顺序生成每条消息                                        │
│  • 每条消息基于前文上下文                                   │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  步骤3: 质量检查（保证准确性）                              │
│  • 检查消息长度（20-500字）                                 │
│  • 检查重复内容                                             │
│  • 检查敏感词                                               │
│  • 质量不合格停止生成                                       │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  步骤4: 串行发送                                            │
│  • 按顺序逐条发送                                           │
│  • 每条间隔2秒                                              │
│  • 失败继续发送下一条                                        │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 核心代码实现

**新增文件**：`src/wecom_automation/servic../03-impl-and-arch/key-modules/batch_reply_simple.py`

```python
"""
极简批量回复生成器（MVP版本）

核心特性：
- 最多3条消息
- 随机决定条数
- AI会话链式生成（保证连贯性）
- 简单质量检查（保证准确性）
"""
import asyncio
import logging
import random
import aiohttp
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import uuid
from datetime import datetime

class BatchIntent(Enum):
    """批量消息意图类型"""
    WELCOME_NEW_USER = "welcome_new_user"    # 欢迎新用户
    PRODUCT_INTRO = "product_intro"          # 产品介绍
    FAQ_REPLY = "faq_reply"                  # FAQ 回复
    PROMOTION = "promotion"                  # 促销推广
    FOLLOW_UP = "follow_up"                  # 跟进消息
    GENERAL = "general"                      # 通用场景

@dataclass
class SimpleBatchRequest:
    """简化的批量生成请求"""
    intent: BatchIntent                      # 意图类型
    customer_name: Optional[str] = None      # 客户名称
    message_count: Optional[int] = None      # 指定条数（1-3），None表示随机

@dataclass
class SimpleBatchResult:
    """简化的批量生成结果"""
    success: bool
    messages: List[str]
    count: int
    total_time: float
    errors: List[str]

class SimpleBatchGenerator:
    """极简批量消息生成器"""

    # 意图特定的提示词模板（保证连贯性）
    INTENT_PROMPTS = {
        BatchIntent.WELCOME_NEW_USER: [
            "生成新用户欢迎语的第1条消息（简洁的问候）",
            "基于上一条欢迎语，生成第2条消息（公司简介）",
            "基于前面的内容，生成第3条消息（核心优势或引导）",
        ],
        BatchIntent.PRODUCT_INTRO: [
            "生成产品介绍的第1条消息（产品概述）",
            "基于上一条，生成第2条消息（核心功能）",
            "基于前面的内容，生成第3条消息（使用场景或优势）",
        ],
        BatchIntent.FAQ_REPLY: [
            "生成FAQ回复的第1条消息（直接回答问题）",
            "基于上一条，生成第2条消息（补充说明）",
            "基于前面的内容，生成第3条消息（引导进一步咨询）",
        ],
        BatchIntent.PROMOTION: [
            "生成促销活动的第1条消息（活动吸引点）",
            "基于上一条，生成第2条消息（具体优惠内容）",
            "基于前面的内容，生成第3条消息（紧迫感或行动召唤）",
        ],
        BatchIntent.FOLLOW_UP: [
            "生成跟进消息的第1条消息（询问近况）",
            "基于上一条，生成第2条消息（提供价值或信息）",
            "基于前面的内容，生成第3条消息（行动召唤）",
        ],
        BatchIntent.GENERAL: [
            "生成第1条消息",
            "基于上一条，生成第2条消息",
            "基于前面的内容，生成第3条消息",
        ],
    }

    def __init__(
        self,
        ai_server_url: str,
        ai_timeout: int = 15,
        logger: Optional[logging.Logger] = None,
    ):
        """
        初始化生成器

        Args:
            ai_server_url: AI 大脑服务地址
            ai_timeout: AI 请求超时时间（秒）
            logger: 日志记录器
        """
        self.ai_server_url = ai_server_url.rstrip('/')
        self.ai_timeout = ai_timeout
        self.logger = logger or logging.getLogger(__name__)

        # 确保以 /chat 结尾
        if not self.ai_server_url.endswith('/chat'):
            self.ai_server_url += '/chat'

    def _decide_count(self, request: SimpleBatchRequest) -> int:
        """
        随机决定回复条数

        策略：
        - 70%概率: 3条
        - 20%概率: 2条
        - 10%概率: 1条
        """
        # 用户指定条数优先
        if request.message_count is not None:
            count = max(1, min(3, request.message_count))
            self.logger.info(f"用户指定条数: {count}")
            return count

        # 随机决定
        rand = random.random()
        if rand < 0.7:
            count = 3
        elif rand < 0.9:
            count = 2
        else:
            count = 1

        self.logger.info(f"随机决定条数: {count} (随机值: {rand:.3f})")
        return count

    async def generate_batch(
        self,
        request: SimpleBatchRequest,
    ) -> SimpleBatchResult:
        """
        批量生成消息（MVP版本）

        Args:
            request: 批量生成请求

        Returns:
            SimpleBatchResult: 生成结果
        """
        start_time = asyncio.get_event_loop().time()

        # 步骤1: 决定条数
        count = self._decide_count(request)

        # 步骤2: 生成统一的sessionId（保证连贯性）
        session_id = f"batch_{request.intent.value}_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}"

        self.logger.info(
            f"开始批量生成: intent={request.intent.value}, "
            f"count={count}, session={session_id}"
        )

        messages = []
        errors = []

        # 步骤3: AI会话链式生成
        for idx in range(count):
            try:
                # 构建提示词（利用会话上下文）
                prompt = self._build_prompt(request, idx)

                self.logger.debug(
                    f"[{idx+1}/{count}] 调用AI (session={session_id})"
                )

                # 调用AI大脑
                message = await self._call_ai_brain(
                    prompt=prompt,
                    session_id=session_id,
                    customer_name=request.customer_name,
                )

                if not message:
                    error_msg = f"消息{idx+1}生成失败：AI返回空"
                    errors.append(error_msg)
                    self.logger.warning(f"[{idx+1}/{count}] ❌ {error_msg}")
                    break

                # 步骤4: 质量检查
                quality_check = self._check_message_quality(message, messages)

                if not quality_check["passed"]:
                    error_msg = f"消息{idx+1}质量检查失败: {quality_check['reason']}"
                    errors.append(error_msg)
                    self.logger.warning(f"[{idx+1}/{count}] ❌ {error_msg}")
                    # 质量不合格，停止生成
                    break

                messages.append(message)
                self.logger.info(
                    f"[{idx+1}/{count}] ✅ 生成成功: {message[:30]}..."
                )

                # 避免请求过快
                if idx < count - 1:
                    await asyncio.sleep(0.5)

            except Exception as e:
                error_msg = f"消息{idx+1}生成异常: {str(e)}"
                errors.append(error_msg)
                self.logger.error(f"[{idx+1}/{count}] ❌ {e}")
                break

        total_time = asyncio.get_event_loop().time() - start_time

        self.logger.info(
            f"批量生成完成: 计划{count}条, 实际{len(messages)}条, "
            f"耗时{total_time:.2f}s"
        )

        return SimpleBatchResult(
            success=len(messages) > 0,
            messages=messages,
            count=len(messages),
            total_time=total_time,
            errors=errors,
        )

    def _build_prompt(self, request: SimpleBatchRequest, index: int) -> str:
        """
        构建提示词

        关键：利用会话上下文，让AI知道这是第几条
        """
        prompts = self.INTENT_PROMPTS.get(request.intent)

        if prompts and index < len(prompts):
            return prompts[index]

        # 默认提示词
        base_prompts = [
            "生成第1条消息",
            "基于上一条，生成第2条消息",
            "基于前面的内容，生成第3条消息",
        ]

        return base_prompts[index] if index < len(base_prompts) else f"生成第{index+1}条消息"

    async def _call_ai_brain(
        self,
        prompt: str,
        session_id: str,
        customer_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        调用AI大脑生成单条消息

        Args:
            prompt: 提示词
            session_id: 会话ID（关键：复用同一会话保证连贯性）
            customer_name: 客户名称（用于metadata）

        Returns:
            生成的消息文本，失败返回None
        """
        payload = {
            "chatInput": prompt,
            "sessionId": session_id,
            "username": f"batch_generator_{session_id}",
            "message_type": "text",
            "metadata": {
                "source": "batch_reply_simple",
                "customer": customer_name or "unknown",
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.ai_server_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.ai_timeout)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        message = data.get("output", "").strip()

                        if message:
                            return message
                        else:
                            self.logger.warning("AI返回空消息")
                            return None
                    else:
                        text = await response.text()
                        self.logger.error(f"AI返回{response.status}: {text}")
                        return None

        except asyncio.TimeoutError:
            self.logger.error(f"AI请求超时（{self.ai_timeout}s）")
            return None
        except Exception as e:
            self.logger.error(f"AI请求异常: {e}")
            return None

    def _check_message_quality(
        self,
        message: str,
        previous_messages: List[str],
    ) -> Dict[str, Any]:
        """
        简单的质量检查

        检查项：
        1. 长度检查（20-500字）
        2. 重复检查
        3. 空值检查

        Returns:
            {"passed": bool, "reason": str}
        """
        # 空值检查
        if not message or not message.strip():
            return {"passed": False, "reason": "消息为空"}

        message = message.strip()
        length = len(message)

        # 长度检查
        if length < 20:
            return {"passed": False, "reason": f"消息过短({length}字)"}
        if length > 500:
            return {"passed": False, "reason": f"消息过长({length}字)"}

        # 重复检查
        for prev_msg in previous_messages:
            if self._similarity(message, prev_msg) > 0.85:
                return {"passed": False, "reason": "与之前消息重复"}

        return {"passed": True, "reason": ""}

    def _similarity(self, msg1: str, msg2: str) -> float:
        """简单的相似度计算"""
        if msg1 == msg2:
            return 1.0

        words1 = set(msg1.split())
        words2 = set(msg2.split())

        if not words1 or not words2:
            return 0.0

        common = words1 & words2
        total = words1 | words2

        return len(common) / len(total)

    async def generate_and_send_batch(
        self,
        request: SimpleBatchRequest,
        wecom_service,
        delay_between: float = 2.0,
    ) -> Dict[str, Any]:
        """
        一站式生成并发送（MVP版本）

        Args:
            request: 批量生成请求
            wecom_service: WeComService实例
            delay_between: 消息间隔（秒）

        Returns:
            完整的生成+发送结果
        """
        # 阶段1: 生成消息
        self.logger.info("阶段1: 生成批量消息...")
        gen_result = await self.generate_batch(request)

        if not gen_result.success or not gen_result.messages:
            return {
                "success": False,
                "error": "生成消息失败",
                "gen_result": gen_result,
            }

        self.logger.info(f"阶段1完成: 生成{gen_result.count}条消息")

        # 阶段2: 串行发送
        self.logger.info("阶段2: 发送批量消息...")

        results = []
        success_count = 0

        for idx, message in enumerate(gen_result.messages):
            try:
                success, actual = await wecom_service.send_message(message)

                results.append({
                    "index": idx,
                    "message": message,
                    "success": success,
                })

                if success:
                    success_count += 1
                    self.logger.info(f"[{idx+1}/{gen_result.count}] ✅ 发送成功")
                else:
                    self.logger.warning(f"[{idx+1}/{gen_result.count}] ❌ 发送失败")

                # 消息间隔（最后一条不需要延迟）
                if idx < gen_result.count - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                self.logger.error(f"[{idx+1}/{gen_result.count}] ❌ 发送异常: {e}")
                results.append({
                    "index": idx,
                    "message": message,
                    "success": False,
                    "error": str(e),
                })

        self.logger.info(f"阶段2完成: {success_count}/{gen_result.count}发送成功")

        return {
            "success": success_count > 0,
            "generation": {
                "planned": request.message_count or "random",
                "generated": gen_result.count,
                "time": gen_result.total_time,
            },
            "sending": {
                "total": gen_result.count,
                "success": success_count,
                "failed": gen_result.count - success_count,
            },
            "messages": gen_result.messages,
            "total_time": gen_result.total_time + (gen_result.count - 1) * delay_between,
        }
```

### 8.4 后端API（极简版）

**文件**：`wecom-desktop/backend/routers/ai_batch_simple.py`

```python
"""
极简批量回复API（MVP版本）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()

class SimpleBatchRequest(BaseModel):
    """批量生成请求"""
    intent: str                     # "welcome_new_user" | "product_intro" | ...
    customerName: Optional[str] = None
    messageCount: Optional[int] = None   # 1-3，None表示随机

class SimpleBatchResponse(BaseModel):
    """批量生成响应"""
    success: bool
    messages: List[str]
    count: int
    planned: str
    totalTime: float
    errors: List[str]

@router.post../03-impl-and-arch/key-modules/batch-generate-simple", response_model=SimpleBatchResponse)
async def batch_generate_simple(request: SimpleBatchRequest):
    """
    极简批量生成API

    Request:
    {
        "intent": "welcome_new_user",
        "customerName": "张三",
        "messageCount": null  # null表示随机（70%概率3条，20%概率2条，10%概率1条）
    }

    Response:
    {
        "success": true,
        "messages": [
            "您好！欢迎添加我们的企业微信～",
            "我们是XX公司，专注于...",
            "有任何问题随时联系我～"
        ],
        "count": 3,
        "planned": "random",
        "totalTime": 8.5,
        "errors": []
    }
    """
    from wecom_automation.services.ai.batch_reply_simple import (
        SimpleBatchGenerator,
        BatchIntent,
        SimpleBatchRequest as AIRequest,
    )
    from services.settings import get_settings_service

    # 获取AI配置
    settings = get_settings_service()
    global_settings = settings.get_flat_settings()
    ai_server_url = global_settings.get('aiServerUrl', 'http://localhost:8000')
    ai_timeout = global_settings.get('aiReplyTimeout', 15)

    # 意图映射
    intent_map = {
        "welcome_new_user": BatchIntent.WELCOME_NEW_USER,
        "product_intro": BatchIntent.PRODUCT_INTRO,
        "faq_reply": BatchIntent.FAQ_REPLY,
        "promotion": BatchIntent.PROMOTION,
        "follow_up": BatchIntent.FOLLOW_UP,
        "general": BatchIntent.GENERAL,
    }

    batch_intent = intent_map.get(request.intent)
    if not batch_intent:
        raise HTTPException(status_code=400, detail=f"Unknown intent: {request.intent}")

    # 构建请求
    ai_request = AIRequest(
        intent=batch_intent,
        customer_name=request.customerName,
        message_count=request.messageCount,
    )

    # 创建生成器
    generator = SimpleBatchGenerator(
        ai_server_url=ai_server_url,
        ai_timeout=ai_timeout,
    )

    # 生成消息
    result = await generator.generate_batch(ai_request)

    return SimpleBatchResponse(
        success=result.success,
        messages=result.messages,
        count=result.count,
        planned=str(request.messageCount) if request.messageCount else "random",
        totalTime=result.total_time,
        errors=result.errors,
    )
```

### 8.5 前端调用示例（极简版）

```typescript
// wecom-desktop/src/services/aiService.ts

export interface SimpleBatchRequest {
  intent: 'welcome_new_user' | 'product_intro' | 'faq_reply' | 'promotion' | 'follow_up' | 'general'
  customerName?: string
  messageCount?: 1 | 2 | 3 // 不指定则随机
}

export interface SimpleBatchResponse {
  success: boolean
  messages: string[]
  count: number
  planned: string
  totalTime: number
  errors: string[]
}

export async function generateSimpleBatch(
  request: SimpleBatchRequest
): Promise<SimpleBatchResponse> {
  const response = await fetch(
    'http://localhost:87../03-impl-and-arch/key-modules/batch-generate-simple',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  )

  return response.json()
}

// 使用示例
const result = await generateSimpleBatch({
  intent: 'welcome_new_user',
  customerName: '张三',
  // messageCount 不指定，随机决定
})

console.log(`生成了${result.count}条消息:`)
result.messages.forEach((msg, idx) => {
  console.log(`${idx + 1}. ${msg}`)
})
```

### 8.6 核心配置（极简版）

```yaml
# config/batch_reply_simple.yaml

batch_reply:
  max_count: 3 # 最多3条
  default_strategy: 'random' # 默认随机策略
  random_distribution: # 随机概率分布
    three: 0.7 # 70%概率3条
    two: 0.2 # 20%概率2条
    one: 0.1 # 10%概率1条

  delay_between: 2.0 # 发送间隔（秒）

  quality_check: # 质量检查
    min_length: 20 # 最短20字
    max_length: 500 # 最长500字
    duplicate_threshold: 0.85 # 重复阈值

  ai:
    timeout: 15 # AI超时（秒）
    retry_on_error: false # 不重试（快速失败）
```

---

## 九、总结（MVP版本）

### 9.1 核心设计要点

**极简MVP，聚焦核心**：

1. **决策层**：随机决定1-3条
   - 70%概率：3条
   - 20%概率：2条
   - 10%概率：1条
   - 用户可手动指定条数

2. **生成层**：AI会话链式生成（保证连贯性）
   - ✅ 使用统一的sessionId
   - ✅ 每条消息基于前文上下文
   - ✅ 意图特定的提示词模板
   - ✅ 简单质量检查（长度、重复）

3. **发送层**：串行发送
   - ✅ 按顺序逐条发送
   - ✅ 每条间隔2秒
   - ✅ 失败继续发送下一条

### 9.2 快速实施计划（MVP）

#### **阶段1: 核心生成器（1天）**

**文件**：`src/wecom_automation/servic../03-impl-and-arch/key-modules/batch_reply_simple.py`

```bash
# 实现内容
- SimpleBatchGenerator 类
- 随机条数决策逻辑
- AI会话链式生成
- 简单质量检查

# 测试
pytest tests/unit/test_batch_reply_simple.py -v
```

#### **阶段2: 后端API（半天）**

**文件**：`wecom-desktop/backend/routers/ai_batch_simple.py`

```bash
# 实现内容
- POS../03-impl-and-arch/key-modules/batch-generate-simple 接口
- 集成 SimpleBatchGenerator
- 错误处理

# 测试
curl -X POST http://localhost:87../03-impl-and-arch/key-modules/batch-generate-simple \
  -H "Content-Type: application/json" \
  -d '{"intent": "welcome_new_user", "customerName": "张三"}'
```

#### **阶段3: 前端集成（半天）**

**文件**：`wecom-desktop/src/services/aiService.ts`

```typescript
// 实现内容
- generateSimpleBatch() 函数
- UI按钮：生成批量回复
- 消息预览和编辑

// 测试
npm run dev:electron
```

#### **阶段4: 端到端测试（半天）**

```bash
# 测试流程
1. 前端点击"批量回复"按钮
2. 后端调用AI生成1-3条消息
3. 前端展示生成的消息
4. 用户确认后发送
5. 验证企业微信收到消息
```

**总计实施时间**：2-3天

### 9.3 关键代码清单

**必需要实现的文件**：

1. **Python生成器**（300行）
   - `src/wecom_automation/servic../03-impl-and-arch/key-modules/batch_reply_simple.py`

2. **后端API**（100行）
   - `wecom-desktop/backend/routers/ai_batch_simple.py`

3. **前端服务**（50行）
   - `wecom-desktop/src/services/aiService.ts`

4. **配置文件**（20行）
   - `config/batch_reply_simple.yaml`

**总代码量**：约500行

### 9.4 核心流程图

```
用户点击"批量回复"
       │
       ▼
┌──────────────────┐
│  前端：显示意图   │
│  选择弹窗        │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  前端：调用API    │
│../03-impl-and-arch/key-modules/batch-      │
│  generate-simple │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  后端：随机决定   │
│  条数（1-3）     │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  AI：会话链式     │
│  生成消息        │
│  (保证连贯性)    │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  质量检查        │
│  (长度、重复)    │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  返回给前端      │
│  显示预览        │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  用户确认        │
│  发送消息        │
└──────────────────┘
```

### 9.5 配置文件（完整版）

```yaml
# config/batch_reply_simple.yaml

batch_reply:
  # 基础配置
  max_count: 3
  default_strategy: 'random'

  # 随机策略配置
  random_distribution:
    three: 0.7 # 70%概率3条
    two: 0.2 # 20%概率2条
    one: 0.1 # 10%概率1条

  # 发送配置
  delay_between: 2.0 # 消息间隔（秒）

  # 质量检查配置
  quality_check:
    enabled: true
    min_length: 20 # 最短20字
    max_length: 500 # 最长500字
    duplicate_threshold: 0.85 # 重复阈值

  # AI配置
  ai:
    timeout: 15 # AI超时（秒）
    retry_on_error: false # 不重试（快速失败）
    delay_between_requests: 0.5 # AI请求间隔（秒）
```

### 9.6 API调用示例

**请求**：

```bash
curl -X POST http://localhost:87../03-impl-and-arch/key-modules/batch-generate-simple \
  -H "Content-Type: application/json" \
  -d '{
    "intent": "welcome_new_user",
    "customerName": "张三"
  }'
```

**响应**：

```json
{
  "success": true,
  "messages": [
    "您好！欢迎添加我们的企业微信～",
    "我们是XX公司，专注于企业数字化解决方案",
    "有任何问题随时联系我～"
  ],
  "count": 3,
  "planned": "random",
  "totalTime": 8.5,
  "errors": []
}
```

### 9.7 使用示例

**前端使用**：

```typescript
// 生成批量消息
const result = await generateSimpleBatch({
  intent: 'welcome_new_user',
  customerName: '张三',
  // messageCount 不指定，随机决定
})

console.log(`生成了${result.count}条消息:`)
result.messages.forEach((msg, idx) => {
  console.log(`${idx + 1}. ${msg}`)
})

// 发送消息
for (const message of result.messages) {
  await sendMessage(message)
  await sleep(2000) // 间隔2秒
}
```

**Python直接使用**：

```python
from wecom_automation.services.ai.batch_reply_simple import (
    SimpleBatchGenerator,
    BatchIntent,
    SimpleBatchRequest
)

# 创建生成器
generator = SimpleBatchGenerator(
    ai_server_url="http://47.113.187.234:8000",
    ai_timeout=15,
)

# 生成消息
request = SimpleBatchRequest(
    intent=BatchIntent.WELCOME_NEW_USER,
    customer_name="张三",
)

result = await generator.generate_batch(request)

print(f"生成了{result.count}条消息:")
for idx, message in enumerate(result.messages):
    print(f"{idx + 1}. {message}")
```

### 9.8 质量保证

**连贯性保证**：

- ✅ 使用统一的sessionId
- ✅ 意图特定的提示词模板
- ✅ 每条消息基于前文上下文

**准确性保证**：

- ✅ 长度检查（20-500字）
- ✅ 重复检查（相似度<85%）
- ✅ 空值检查
- ✅ 质量不合格停止生成

**可靠性保证**：

- ✅ 异常处理
- ✅ 超时控制
- ✅ 日志记录
- ✅ 快速失败（不重试）

### 9.9 后续优化方向（可选）

MVP上线后，根据实际效果和数据，可以考虑：

1. **数据分析**
   - 统计1/2/3条的使用频率
   - 分析响应率差异
   - 收集用户反馈

2. **策略优化**
   - 根据数据调整随机概率
   - 为不同场景定制策略
   - A/B测试不同方案

3. **功能增强**
   - 添加消息编辑功能
   - 添加发送历史记录
   - 添加效果追踪

### 9.10 预期效果

| 指标         | MVP版本 | 说明                              |
| ------------ | ------- | --------------------------------- |
| 实施时间     | 2-3天   | 极简快速                          |
| 代码量       | ~500行  | 易于维护                          |
| 消息连贯性   | 高      | AI会话链式保证                    |
| 消息准确性   | 高      | 质量检查保证                      |
| 平均生成条数 | 2.6条   | 随机策略（70%×3 + 20%×2 + 10%×1） |
| 生成耗时     | 6-10秒  | 3条消息×2-3秒/条                  |

---

**文档版本**: v4.0 (MVP版本)
**最后更新**: 2026-01-24
**作者**: Claude Code (Architecture Design)
**审核状态**: 待审核
**更新内容**:

- v3.0 → v4.0: 简化为MVP版本
- 删除复杂的智能决策逻辑
- 删除疲劳度管理、A/B测试等高级功能
- 保留核心：AI会话链式生成（保证连贯性）
- 保留核心：简单质量检查（保证准确性）
- 新增极简随机策略（1-3条）
- 新增快速实施计划（2-3天）
