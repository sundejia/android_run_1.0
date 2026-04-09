"""
AI Analysis Service for Streamer Persona Generation.

Uses configurable AI providers (DeepSeek, OpenAI, etc.) to analyze
conversation history and generate personality/communication insights.
"""

import json
import os
from typing import Any, Dict, List, Optional

import httpx


# Default settings - can be overridden via API
DEFAULT_PROVIDER = "deepseek"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-d98ab8a7e2694ed99b70eecd54b1643d")
DEFAULT_MAX_TOKENS = 4096


def get_ai_settings() -> Dict[str, str]:
    """Get AI settings from environment or defaults."""
    return {
        "provider": os.environ.get("AI_ANALYSIS_PROVIDER", DEFAULT_PROVIDER),
        "base_url": os.environ.get("AI_ANALYSIS_BASE_URL", DEFAULT_BASE_URL),
        "api_key": os.environ.get("AI_ANALYSIS_API_KEY", DEFAULT_API_KEY),
        "model": os.environ.get("AI_ANALYSIS_MODEL", DEFAULT_MODEL),
    }


PERSONA_ANALYSIS_PROMPT = """你是一位专业的社交媒体公司数据科学家，专门分析主播候选人的性格特征和沟通风格。

请分析以下来自主播 "{name}" 的聊天消息，并生成详细的人物画像分析报告。

消息内容：
{messages}

请以JSON格式返回分析结果，包含以下字段：

{{
    "communication_style": "沟通风格描述（1-2句话）",
    "language_patterns": ["语言特征1", "语言特征2", "语言特征3"],
    "tone": "语气特点描述",
    "engagement_level": "参与度评估（高/中/低）及说明",
    "response_time_pattern": "回复时间规律描述",
    "active_hours": ["活跃时段1", "活跃时段2"],
    "topics_of_interest": ["兴趣话题1", "兴趣话题2", "兴趣话题3"],
    "personality_traits": ["性格特征1", "性格特征2", "性格特征3"],
    "dimensions": [
        {{"name": "外向性", "value": 0-100, "description": "描述"}},
        {{"name": "开放性", "value": 0-100, "description": "描述"}},
        {{"name": "尽责性", "value": 0-100, "description": "描述"}},
        {{"name": "宜人性", "value": 0-100, "description": "描述"}},
        {{"name": "情绪稳定性", "value": 0-100, "description": "描述"}}
    ],
    "analysis_summary": "综合分析总结（2-3句话）",
    "recommendations": [
        "与该主播沟通的建议1",
        "与该主播沟通的建议2",
        "与该主播沟通的建议3"
    ]
}}

请确保：
1. 所有分析基于提供的消息内容
2. dimensions中的value值在0-100之间
3. 返回有效的JSON格式
4. 使用中文回复
"""


async def analyze_streamer_persona(
    name: str,
    messages: List[str],
    settings: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Analyze a streamer's persona using AI.

    Args:
        name: Streamer's name
        messages: List of message content from the streamer
        settings: Optional AI settings override

    Returns:
        Dictionary containing persona analysis results
    """
    ai_settings = settings or get_ai_settings()

    # Prepare messages for the prompt (limit to avoid token limits)
    message_sample = messages[:200]  # Take first 200 messages
    formatted_messages = "\n".join([f"- {msg}" for msg in message_sample])

    prompt = PERSONA_ANALYSIS_PROMPT.format(
        name=name,
        messages=formatted_messages,
    )

    # Build request based on provider
    provider = ai_settings.get("provider", DEFAULT_PROVIDER)
    base_url = ai_settings.get("base_url", DEFAULT_BASE_URL)
    api_key = ai_settings.get("api_key", DEFAULT_API_KEY)
    model = ai_settings.get("model", DEFAULT_MODEL)

    if provider == "deepseek":
        url = f"{base_url}/chat/completions"
    elif provider == "openai":
        url = f"{base_url}/v1/chat/completions"
    else:
        url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一位专业的社交媒体数据分析师，擅长分析用户行为和性格特征。请以JSON格式返回分析结果。",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            error_detail = response.json().get("error", {}).get("message", response.text)
            raise Exception(f"AI API error: {error_detail}")

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Parse JSON response
        try:
            analysis = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            import re

            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                raise Exception("Failed to parse AI response as JSON")

        # Add model info
        analysis["model_used"] = model

        return analysis


async def test_ai_connection(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
) -> Dict[str, Any]:
    """
    Test the AI provider connection.

    Returns:
        Dictionary with success status and latency
    """
    import time

    start_time = time.time()

    if provider == "deepseek":
        url = f"{base_url}/chat/completions"
    elif provider == "openai":
        url = f"{base_url}/v1/chat/completions"
    else:
        url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 10,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    latency_ms = int((time.time() - start_time) * 1000)

    if response.status_code == 200:
        return {
            "success": True,
            "message": "Connected successfully",
            "latency_ms": latency_ms,
        }
    else:
        error_detail = response.json().get("error", {}).get("message", response.text)
        return {
            "success": False,
            "error": f"API error: {error_detail}",
            "latency_ms": latency_ms,
        }
