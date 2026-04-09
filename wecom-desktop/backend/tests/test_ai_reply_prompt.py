"""
AI 回复 Prompt 测试脚本

基于真实聊天记录测试 AI 回复效果。
可以独立运行，不依赖其他服务（除了 AI 服务本身）。

Usage:
    cd wecom-desktop/backend
    python tests/test_ai_reply_prompt.py
    
    # 测试补刀场景
    python tests/test_ai_reply_prompt.py --followup
    
    # 使用自定义 AI 服务器
    python tests/test_ai_reply_prompt.py --server http://localhost:8000
"""

import asyncio
import argparse
import json
import sys
import io
from typing import Optional
from dataclasses import dataclass


def _setup_windows_encoding():
    """设置 Windows 控制台编码，仅在直接运行脚本时调用"""
    if sys.platform == "win32" and hasattr(sys.stdout, 'buffer'):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass  # 忽略编码设置错误（如在 pytest 环境中）


# ============================================
# 配置
# ============================================

DEFAULT_AI_SERVER = "http://47.113.187.234:8000/chat"
DEFAULT_TIMEOUT = 30

# 预设风格（与 service.py 中的 PROMPT_STYLE_PRESETS 一致）
PROMPT_STYLE_PRESETS = {
    "none": "",
    "default": """语气礼貌大方，使用"您"称呼用户。
回答要直接且有条理，避免冗长。
始终保持耐心，无论用户的情绪如何。""",
    "lively": """语气要超级热情，多使用"哈喽"、"亲亲"、"么么哒"或"好哒"等词汇。
适当使用表情符号（如 🌈, 🚀, 😊）来让对话更生动。
把用户当成朋友，除了解决问题，也要给用户提供情绪价值。
遇到用户抱怨时，要用超温柔的方式安抚对方，比如："抱抱亲亲，别生气哦，小趣马上帮你想办法！" """,
    "professional": """使用极其正式的商务用语，确保表达的准确性。
回答问题时，请适度采用"第一步、第二步、第三步"的结构化方式。
引用任何数据或政策时需谨慎核实，确保专业度。
保持绝对客观中立，即使在拒绝用户要求时，也要解释清楚基于的政策条款。""",
    "minimal": """拒绝寒暄。直接识别用户意图并给出答案。
使用精炼的短句，不要使用任何修辞手法。
如果问题需要多个步骤，仅提供最直接的解决方案链接或指令。""",
}


# ============================================
# 测试数据 - 基于截图的真实聊天记录
# ============================================

@dataclass
class Message:
    """聊天消息"""
    is_self: bool  # True = Agent(客服), False = Customer(客户)
    content: str
    message_type: str = "text"


# 从截图提取的聊天记录
SAMPLE_CONVERSATION = [
    Message(is_self=False, content="我是柠檬"),
    # 系统消息（不计入对话）
    Message(is_self=True, content="感谢您信任并选择WELIKE，未来我将会在该账号与您保持沟通。"),
    Message(is_self=True, content="Hello，我是BOSS上和你联系的，先简单介绍一下公司。我们是全网直播经纪公司，年流水2个亿，优势是流量运营，主播收入日结且有保底。你好呀小姐姐，咱们怎么称呼你呢？"),
    Message(is_self=False, content="柠檬"),
    Message(is_self=False, content="哪个公司呀"),
    Message(is_self=True, content="柠檬你好，这边需要先了解你几个问题。以前有直播经历吗？在哪个平台呢？"),
    Message(is_self=False, content="招经纪人吗"),
    Message(is_self=True, content="柠檬你好，我们目前主要招募主播。请问你之前有直播经历吗？在哪个平台呢？"),
    Message(is_self=False, content="不当主播"),  # 最新客户消息
]

CUSTOMER_NAME = "柠檬"


# ============================================
# XML 结构化 Prompt 构建逻辑（与 response_detector.py 一致）
# ============================================

def build_context_string(messages: list) -> str:
    """构建对话历史字符串"""
    context_lines = []
    for msg in messages:
        role = "AGENT" if msg.is_self else "CUSTOMER"
        content = msg.content or "[media]"
        if msg.message_type and msg.message_type != "text":
            content = f"[{msg.message_type}] {content}" if content != "[media]" else f"[{msg.message_type}]"
        context_lines.append(f"{role}: {content}")
    return "\n".join(context_lines)


def build_style_guidelines(custom_prompt: str = "", style_key: str = "default") -> str:
    """构建风格指南"""
    style_prompt = PROMPT_STYLE_PRESETS.get(style_key, "")
    
    if custom_prompt and style_prompt:
        return f"{custom_prompt}\n\n{style_prompt}"
    return custom_prompt or style_prompt or "使用礼貌、友好的语气。"


def build_xml_prompt_normal(
    customer_name: str,
    messages: list,
    last_customer_msg: str,
    style_guidelines: str,
    max_length: int = 50,
) -> str:
    """
    构建正常回复场景的 XML 结构化 Prompt
    """
    context = build_context_string(messages)
    
    return f"""<task>
为客户 {customer_name} 的最新消息生成一条合适的回复。
</task>

<context>
<scenario>实时回复场景</scenario>
<customer_name>{customer_name}</customer_name>
<situation>客户发送了新消息，需要及时、恰当地回复。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，同时需要专业地处理各种客户咨询。</business_background>
</context>

<conversation_history count="{len(messages)}">
{context}
</conversation_history>

<latest_customer_message>
{last_customer_msg}
</latest_customer_message>

<style_guidelines>
{style_guidelines}
</style_guidelines>

<requirements>
<functional>
1. 针对客户的最新消息进行回复
2. 回复要解决客户的问题或回应客户的诉求
3. 保持对话的连贯性和上下文关联
</functional>
<content_rules>
1. 仔细阅读完整对话历史，理解客户需求和背景
2. 回复要自然、礼貌，与之前的对话风格保持一致
3. 如果是延续之前的话题，要有上下文连贯性
4. 简洁明了，不要重复之前已经说过的内容
</content_rules>
</requirements>

<constraints>
<forbidden_patterns>
1. 禁止忽视客户的问题而转移话题
2. 禁止使用模板化的敷衍回复
3. 禁止重复之前已经说过的内容
</forbidden_patterns>
<special_commands>
如果客户要求转人工、找真人客服、或表示要人工服务，直接返回: command back to user operation
</special_commands>
</constraints>

<thinking>
在生成回复之前，请按以下步骤思考：
1. 理解客户最新消息的真实意图和诉求
2. 回顾对话历史，确保回复具有上下文连贯性
3. 判断是否需要转人工处理
4. 根据 style_guidelines 调整回复的语气和风格
5. 确保回复直接解决客户的问题
</thinking>

<output_format>
直接输出回复消息文本，不要包含任何解释、标签或格式标记。
</output_format>"""


def build_xml_prompt_followup(
    customer_name: str,
    messages: list,
    followup_prompt: str,
    style_guidelines: str,
    max_length: int = 50,
) -> str:
    """
    构建补刀场景的 XML 结构化 Prompt
    """
    context = build_context_string(messages)
    
    return f"""<task>
为客户 {customer_name} 生成一条主动跟进消息。该客户已长时间未回复，需要友好地重新激活对话。
</task>

<context>
<scenario>补刀跟进场景</scenario>
<customer_name>{customer_name}</customer_name>
<situation>客户已经长时间未回复消息，需要主动发起跟进以重新激活对话。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，需要在保持专业的同时展现诚意。</business_background>
</context>

<conversation_history count="{len(messages)}">
{context}
</conversation_history>

<custom_instructions>
{followup_prompt}
</custom_instructions>

<style_guidelines>
{style_guidelines}
</style_guidelines>

<requirements>
<functional>
1. 生成一条自然的跟进消息，重新激活与客户的对话
2. 消息应该友好、不带压迫感
3. 可以询问客户近况或提供新的价值信息
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
如果判断客户明确表示不感兴趣或要求转人工，直接返回: command back to user operation
</special_commands>
</constraints>

<thinking>
在生成消息之前，请按以下步骤思考：
1. 回顾对话历史，理解客户的态度和之前的交流内容
2. 分析客户最后一条消息的语气和意图
3. 思考什么样的跟进方式最不会让客户反感
4. 确保消息内容不重复之前说过的话
5. 根据 custom_instructions 中的风格要求调整语气
</thinking>

<output_format>
直接输出跟进消息文本，不要包含任何解释、标签或格式标记。
</output_format>"""


# ============================================
# AI 服务调用
# ============================================

async def call_ai_service(
    ai_server: str,
    xml_prompt: str,
    session_id: str = "test_session",
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """调用 AI 服务（使用 XML 结构化 Prompt）"""
    import aiohttp
    
    payload = {
        "chatInput": xml_prompt,
        "sessionId": session_id,
        "username": "test_user",
        "message_type": "text",
        "metadata": {
            "source": "test_ai_reply_prompt",
            "prompt_format": "xml_structured",
        },
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ai_server,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # 尝试多种响应格式
                    reply = (
                        result.get("output")
                        or result.get("response")
                        or result.get("text")
                        or result.get("message")
                        or str(result)
                    )
                    return reply
                else:
                    error_text = await response.text()
                    print(f"❌ AI 服务返回错误: {response.status}")
                    print(f"   响应内容: {error_text[:200]}")
                    return None
    except asyncio.TimeoutError:
        print(f"❌ AI 服务超时 ({timeout}s)")
        return None
    except Exception as e:
        print(f"❌ 调用 AI 服务失败: {e}")
        return None


# ============================================
# 主测试函数
# ============================================

async def test_ai_reply(
    is_followup: bool = False,
    followup_prompt: str = "",
    custom_system_prompt: str = "",
    style_key: str = "default",
    max_length: int = 50,
    ai_server: str = DEFAULT_AI_SERVER,
):
    """
    测试 AI 回复（XML 结构化 Prompt）
    
    Args:
        is_followup: 是否为补刀场景
        followup_prompt: 补刀提示词（仅补刀场景使用）
        custom_system_prompt: 自定义系统提示词
        style_key: 预设风格 (none/default/lively/professional/minimal)
        max_length: 回复最大长度
        ai_server: AI 服务器地址
    """
    print("=" * 70)
    print("AI 回复 Prompt 测试 (XML 结构化格式)")
    print("=" * 70)
    
    # 1. 构建风格指南
    style_guidelines = build_style_guidelines(custom_system_prompt, style_key)
    
    # 2. 构建 XML 结构化 Prompt
    if is_followup:
        # 补刀场景
        default_followup = "请生成一条友好的跟进消息，不要太有压迫感，让客户感受到我们的诚意"
        actual_followup_prompt = followup_prompt or default_followup
        xml_prompt = build_xml_prompt_followup(
            CUSTOMER_NAME,
            SAMPLE_CONVERSATION,
            actual_followup_prompt,
            style_guidelines,
            max_length,
        )
        scenario = "补刀（跟进）"
    else:
        # 正常回复场景
        last_customer_msg = ""
        for msg in reversed(SAMPLE_CONVERSATION):
            if not msg.is_self:
                last_customer_msg = msg.content
                break
        xml_prompt = build_xml_prompt_normal(
            CUSTOMER_NAME,
            SAMPLE_CONVERSATION,
            last_customer_msg,
            style_guidelines,
            max_length,
        )
        scenario = "正常回复"
    
    # 3. 打印 XML Prompt 结构摘要
    print(f"\n📋 场景: {scenario}")
    print(f"👤 客户: {CUSTOMER_NAME}")
    print(f"🎨 风格: {style_key}")
    print(f"📏 最大长度: {max_length} 字")
    print(f"🌐 AI 服务器: {ai_server}")
    print(f"📝 Prompt 格式: XML Structured")
    
    print("\n" + "-" * 70)
    print("📝 XML 结构化 Prompt (chatInput):")
    print("-" * 70)
    print(xml_prompt)
    
    # 4. 调用 AI 服务
    print("\n" + "=" * 70)
    print("🤖 正在调用 AI 服务...")
    print("=" * 70)
    
    reply = await call_ai_service(
        ai_server=ai_server,
        xml_prompt=xml_prompt,
        session_id=f"test_{CUSTOMER_NAME}",
    )
    
    if reply:
        print(f"\n✅ AI 回复:")
        print("-" * 70)
        print(reply)
        print("-" * 70)
        print(f"📏 回复长度: {len(reply)} 字")
    else:
        print("\n❌ 未能获取 AI 回复")
    
    return reply


def main():
    parser = argparse.ArgumentParser(description="测试 AI 回复 Prompt")
    parser.add_argument(
        "--followup", "-f",
        action="store_true",
        help="测试补刀场景（默认为正常回复场景）"
    )
    parser.add_argument(
        "--followup-prompt", "-fp",
        type=str,
        default="",
        help="补刀提示词（仅补刀场景使用）"
    )
    parser.add_argument(
        "--system-prompt", "-sp",
        type=str,
        default="",
        help="自定义系统提示词"
    )
    parser.add_argument(
        "--style", "-s",
        type=str,
        default="default",
        choices=["none", "default", "lively", "professional", "minimal"],
        help="预设风格"
    )
    parser.add_argument(
        "--max-length", "-l",
        type=int,
        default=50,
        help="回复最大长度（字）"
    )
    parser.add_argument(
        "--server",
        type=str,
        default=DEFAULT_AI_SERVER,
        help="AI 服务器地址"
    )
    
    args = parser.parse_args()
    
    # 确保服务器地址以 /chat 结尾
    ai_server = args.server
    if not ai_server.endswith("/chat"):
        ai_server = ai_server.rstrip("/") + "/chat"
    
    asyncio.run(test_ai_reply(
        is_followup=args.followup,
        followup_prompt=args.followup_prompt,
        custom_system_prompt=args.system_prompt,
        style_key=args.style,
        max_length=args.max_length,
        ai_server=ai_server,
    ))


if __name__ == "__main__":
    _setup_windows_encoding()
    main()
