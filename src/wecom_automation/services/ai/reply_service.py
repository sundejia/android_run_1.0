"""
AI回复服务

提供AI生成回复的能力，用于自动回复消息。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from wecom_automation.core.interfaces import IAIReplyService, MessageContext


class AIReplyService(IAIReplyService):
    """
    AI回复服务

    职责:
    - 生成AI回复
    - 格式化会话上下文
    - 检测转人工请求

    Usage:
        async with AIReplyService(server_url) as service:
            reply = await service.get_reply(message, context, history)
            if service.is_human_request(reply):
                # 处理转人工
                pass
    """

    # 转人工命令
    HUMAN_REQUEST_COMMAND = "command back to user operation"

    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        timeout: int = 10,
        system_prompt: str | None = None,
        logger: logging.Logger | None = None,
        email_config: dict[str, Any] | None = None,
    ):
        """
        初始化AI回复服务

        Args:
            server_url: AI服务器URL
            timeout: 请求超时时间（秒）
            system_prompt: 系统提示词
            logger: 日志记录器
            email_config: 邮件通知配置（可选）
        """
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.system_prompt = system_prompt
        self._logger = logger or logging.getLogger(__name__)
        self._session: aiohttp.ClientSession | None = None
        self.email_config = email_config

        # 构建增强的系统提示词
        self._enhanced_prompt = self._build_enhanced_prompt()

    def _build_enhanced_prompt(self) -> str:
        """构建增强的系统提示词"""
        base = self.system_prompt.strip() if self.system_prompt else ""

        human_detection = (
            "If the user wants to switch to human operation, human agent, "
            "or manual service, directly return ONLY the text "
            "'command back to user operation' without any other text."
        )

        if base:
            return f"{base}\n\n{human_detection}"
        return human_detection

    async def __aenter__(self):
        """进入异步上下文"""
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, *args):
        """退出异步上下文"""
        if self._session:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if not self._session:
            raise RuntimeError("AIReplyService not initialized. Use 'async with' context manager.")
        return self._session

    async def get_reply(
        self, message: str, context: MessageContext, history: list[dict[str, Any]] | None = None
    ) -> str | None:
        """
        获取AI回复

        Args:
            message: 用户消息
            context: 消息上下文
            history: 历史消息列表

        Returns:
            AI生成的回复，失败返回None
        """
        self._logger.info(f"Getting AI reply for: {message[:50]}...")

        # 解析消息获取提示词
        prompt = self._parse_message(message)

        # 格式化会话上下文
        if history:
            formatted_prompt = self._format_conversation_context(history, prompt)
        else:
            formatted_prompt = f"[LATEST MESSAGE]\n{prompt}"

        try:
            # XML 结构化 prompt 已经包含所有内容，直接使用
            final_input = formatted_prompt

            # 截断以符合长度限制（XML 格式）
            final_input = self._truncate_input(final_input, 2000)

            # 构建请求
            payload = {
                "chatInput": final_input,
                "sessionId": f"sync_{context.device_serial}_{int(datetime.now().timestamp())}",
                "username": f"sync_{context.device_serial}",
                "message_type": "text",
                "metadata": {
                    "source": "sync_service",
                    "serial": context.device_serial,
                    "original_message": message,
                },
            }

            # ===== AI Request Logging (XML Structured) =====
            scenario = "补刀跟进" if ("补刀" in message or "想的怎么样" in message) else "实时回复"
            self._logger.info("=" * 60)
            self._logger.info(f"AI REQUEST for {context.customer_name} [{scenario}]")
            self._logger.info("=" * 60)
            self._logger.info(f"AI Server: {self.server_url}/chat")
            self._logger.info(f"Timeout: {self.timeout}s")
            self._logger.info(f"Session ID: {payload['sessionId']}")
            self._logger.info(f"Device: {context.device_serial}")
            self._logger.info("Prompt Format: XML Structured")
            self._logger.info("")
            self._logger.info("--- XML Prompt Structure ---")
            self._logger.info(
                f"<task> 为 {context.customer_name} 生成{'跟进消息' if scenario == '补刀跟进' else '回复'}"
            )
            self._logger.info(f"<context> 场景={scenario}")
            self._logger.info(f"<conversation_history> {len(history) if history else 0} 条消息")
            self._logger.info(f"<style_guidelines> {(self.system_prompt or '默认风格')[:40]}...")
            self._logger.info("<constraints> special_commands=转人工检测")
            if history:
                self._logger.info("")
                self._logger.info(f"--- Conversation History ({len(history)} messages) ---")
                # 显示最后 10 条消息
                display_history = history[-10:] if len(history) > 10 else history
                if len(history) > 10:
                    self._logger.info(f"(Showing last 10 of {len(history)} messages)")
                for idx, msg in enumerate(display_history):
                    role = "AGENT" if msg.get("is_from_kefu", False) else "STREAMER"
                    content = msg.get("content", "")[:100]
                    self._logger.info(f"[{idx + 1}] {role}: {content}...")
            self._logger.info("=" * 60)

            # 发送请求
            async with self.session.post(f"{self.server_url}/chat", json=payload) as resp:
                # ===== AI Response Logging =====
                self._logger.info("=" * 60)
                self._logger.info(f"AI RESPONSE for {context.customer_name}")
                self._logger.info("=" * 60)
                self._logger.info(f"HTTP Status: {resp.status}")

                if resp.status != 200:
                    error_text = await resp.text()
                    self._logger.error(f"Response body: {error_text[:500]}")
                    self._logger.info("=" * 60)
                    return None

                data = await resp.json()
                self._logger.info(f"Response Data: {data}")

                if data.get("success") and data.get("output"):
                    output = data["output"]
                    self._logger.info("")
                    self._logger.info("--- AI Reply ---")
                    self._logger.info(f"{output}")
                    self._logger.info("=" * 60)
                    return output
                else:
                    self._logger.warning("AI response not successful")
                    self._logger.info("=" * 60)
                    return None

        except TimeoutError:
            self._logger.error("=" * 60)
            self._logger.error("AI REQUEST TIMEOUT")
            self._logger.error("=" * 60)
            self._logger.error(f"Customer: {context.customer_name}")
            self._logger.error(f"Timeout after: {self.timeout}s")
            self._logger.error(f"AI Server: {self.server_url}/chat")
            self._logger.error("=" * 60)
            return None
        except Exception as e:
            self._logger.error("=" * 60)
            self._logger.error("AI REQUEST ERROR")
            self._logger.error("=" * 60)
            self._logger.error(f"Customer: {context.customer_name}")
            self._logger.error(f"Error: {e}")
            self._logger.error(f"AI Server: {self.server_url}/chat")
            import traceback

            self._logger.error(f"Traceback:\n{traceback.format_exc()}")
            self._logger.error("=" * 60)
            return None

    def is_human_request(self, reply: str) -> bool:
        """
        检查回复是否表示转人工请求

        Args:
            reply: AI的回复

        Returns:
            True如果是转人工请求
        """
        if not reply:
            return False
        return self.HUMAN_REQUEST_COMMAND in reply.lower()

    def _parse_message(self, message: str) -> str:
        """
        解析消息获取提示词

        支持格式:
        - "测试信息: 想的怎么样了?" -> 跟进提示
        - "测试信息: [...content...]" -> 提取内容

        Args:
            message: 原始消息

        Returns:
            提示词
        """
        import re

        trimmed = message.strip()

        # 检查是否是测试消息
        if not (trimmed.startswith("测试信息:") or trimmed.startswith("测试信息：")):
            return trimmed

        # 提取内容
        match = re.match(r"^测试信息[:：]\s*(.*)$", trimmed)
        if not match:
            return trimmed

        content = match.group(1).strip()

        # 跟进模式
        if content in ("想的怎么样了?", "想的怎么样了？"):
            return '主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系'

        # [...content...] 格式
        bracket_match = re.match(r"^\[\.\.\.(.+?)\.\.\.\]$", content)
        if bracket_match:
            return bracket_match.group(1).strip()

        return content

    def _format_conversation_context(
        self, history: list[dict[str, Any]], current_message: str, max_length: int = 800
    ) -> str:
        """
        格式化会话上下文（XML 结构化格式）

        Args:
            history: 历史消息列表
            current_message: 当前消息
            max_length: 最大长度

        Returns:
            格式化后的上下文字符串
        """
        # 构建对话历史字符串
        context_lines = []
        for msg in history:
            content = msg.get("content", "")
            is_from_kefu = msg.get("is_from_kefu", False)

            if not content or not content.strip():
                continue

            role = "AGENT" if is_from_kefu else "STREAMER"
            context_lines.append(f"{role}: {content}")

        context_history = "\n".join(context_lines) if context_lines else "无历史消息"

        # 判断是否为补刀场景
        is_followup = "补刀" in current_message or "想的怎么样" in current_message

        # 构建 XML 结构化 prompt
        if is_followup:
            # 补刀跟进场景
            xml_prompt = f"""<task>
为主播生成一条主动跟进消息。该主播已长时间未回复，需要友好地重新激活对话。
</task>

<context>
<scenario>全量同步补刀场景</scenario>
<situation>主播已经长时间未回复消息，需要主动发起跟进以重新激活对话。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，需要在保持专业的同时展现诚意。</business_background>
</context>

<conversation_history count="{len(history) if history else 0}">
{context_history}
</conversation_history>

<custom_instructions>
{current_message}
</custom_instructions>

<system_prompt>
{self.system_prompt if self.system_prompt else "使用礼貌、友好的语气。"}
</system_prompt>

<requirements>
<functional>
1. 生成一条自然的跟进消息，重新激活与主播的对话
2. 消息应该友好、不带压迫感
3. 可以询问主播近况或提供新的价值信息
</functional>
<content_rules>
1. 不要重复之前已经说过的内容
2. 不要过于急切或有销售压力
3. 保持与之前对话风格的一致性
4. 消息要自然，像是正常的后续关心
</content_rules>
</requirements>

<constraints>
<forbidden_patterns>
1. 禁止使用"打扰了"等负面开场
2. 禁止连续发送相同或相似内容
3. 禁止过度推销或施压
</forbidden_patterns>
<special_commands>
如果判断主播明确表示不感兴趣或要求转人工，直接返回: command back to user operation
</special_commands>
</constraints>

<thinking>
在生成消息之前，请按以下步骤思考：
1. 回顾对话历史，理解主播的态度和之前的交流内容
2. 分析主播最后一条消息的语气和意图
3. 思考什么样的跟进方式最不会让主播反感
4. 确保消息内容不重复之前说过的话
5. 根据 custom_instructions 中的风格要求调整语气
</thinking>

<output_format>
直接输出跟进消息文本，不要包含任何解释、标签或格式标记。
</output_format>"""
        else:
            # 正常回复场景
            xml_prompt = f"""<task>
为主播的最新消息生成一条合适的回复。
</task>

<context>
<scenario>全量同步实时回复场景</scenario>
<situation>主播发送了新消息，需要及时、恰当地回复。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，同时需要专业地处理各种主播咨询。</business_background>
</context>

<conversation_history count="{len(history) if history else 0}">
{context_history}
</conversation_history>

<latest_customer_message>
{current_message}
</latest_customer_message>

<style_guidelines>
{self.system_prompt if self.system_prompt else "使用礼貌、友好的语气。"}
</style_guidelines>

<requirements>
<functional>
1. 针对主播的最新消息进行回复
2. 回复要解决主播的问题或回应主播的诉求
3. 保持对话的连贯性和上下文关联
</functional>
<content_rules>
1. 仔细阅读完整对话历史，理解主播需求和背景
2. 回复要自然、礼貌，与之前的对话风格保持一致
3. 如果是延续之前的话题，要有上下文连贯性
4. 简洁明了，不要重复之前已经说过的内容
</content_rules>
</requirements>

<constraints>
<forbidden_patterns>
1. 禁止忽视主播的问题而转移话题
2. 禁止使用模板化的敷衍回复
3. 禁止重复之前已经说过的内容
</forbidden_patterns>
<special_commands>
如果主播要求转人工、找真人客服、或表示要人工服务，直接返回: command back to user operation
</special_commands>
</constraints>

<thinking>
在生成回复之前，请按以下步骤思考：
1. 理解主播最新消息的真实意图和诉求
2. 回顾对话历史，确保回复具有上下文连贯性
3. 判断是否需要转人工处理
4. 根据 style_guidelines 调整回复的语气和风格
5. 确保回复直接解决主播的问题
</thinking>

<output_format>
直接输出回复消息文本，不要包含任何解释、标签或格式标记。
</output_format>"""

        # 如果超长，逐步删除旧消息
        while len(xml_prompt) > max_length and context_lines:
            context_lines.pop(0)
            context_history = "\n".join(context_lines) if context_lines else "无历史消息"
            # 重新构建（简化版，只更新 conversation_history 部分）
            if is_followup:
                xml_prompt = xml_prompt.replace(
                    f'<conversation_history count="{len(history) if history else 0}">',
                    f'<conversation_history count="{len(context_lines)}">',
                )

        return xml_prompt

    def _truncate_input(self, input_text: str, max_length: int = 1000) -> str:
        """
        截断输入以符合长度限制

        Args:
            input_text: 输入文本
            max_length: 最大长度

        Returns:
            截断后的文本
        """
        if len(input_text) <= max_length:
            return input_text

        self._logger.warning(f"Input too long ({len(input_text)} chars), truncating to {max_length}")

        # 尝试智能截断
        import re

        match = re.match(r"^.*?system_prompt: ([\s\S]*?)\nuser_prompt: ", input_text)

        if match:
            system_part = match.group(0)
            user_part = input_text[len(system_part) :]

            available = max_length - len(system_part)
            if available > 100:
                return system_part + user_part[-available:]

        # 简单截断
        keep_start = int(max_length * 0.3)
        keep_end = max_length - keep_start - 20
        return input_text[:keep_start] + "\n...[truncated]...\n" + input_text[-keep_end:]
