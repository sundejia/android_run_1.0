"""
同步选项配置

提供同步选项的数据类和工厂方法。
"""

from typing import Any

# 重新导出接口模块中的 SyncOptions
from wecom_automation.core.interfaces import SyncOptions


def create_sync_options(
    send_test_messages: bool = True,
    response_wait_seconds: float = 5.0,
    prioritize_unread: bool = False,
    unread_only: bool = False,
    resume: bool = False,
    timing_multiplier: float = 1.0,
    interactive_wait_timeout: float = 40.0,
    max_interaction_rounds: int = 10,
    dynamic_unread_detection: bool = True,
    **kwargs,
) -> SyncOptions:
    """
    创建同步选项

    工厂方法，便于从各种来源创建 SyncOptions。

    Args:
        send_test_messages: 是否发送测试消息
        response_wait_seconds: 等待响应的秒数
        prioritize_unread: 是否优先同步未读消息用户
        unread_only: 是否仅同步有未读消息的用户
        resume: 是否从断点续传
        timing_multiplier: 延迟时间倍数
        interactive_wait_timeout: 交互式等待超时（秒）
        max_interaction_rounds: 最大交互轮次
        dynamic_unread_detection: 是否启用动态未读检测
        **kwargs: 忽略额外参数

    Returns:
        SyncOptions 实例
    """
    return SyncOptions(
        send_test_messages=send_test_messages,
        response_wait_seconds=response_wait_seconds,
        prioritize_unread=prioritize_unread,
        unread_only=unread_only,
        resume=resume,
        timing_multiplier=timing_multiplier,
        interactive_wait_timeout=interactive_wait_timeout,
        max_interaction_rounds=max_interaction_rounds,
        dynamic_unread_detection=dynamic_unread_detection,
    )


def options_from_args(args) -> SyncOptions:
    """
    从命令行参数创建同步选项

    Args:
        args: argparse.Namespace 对象

    Returns:
        SyncOptions 实例
    """
    return SyncOptions(
        send_test_messages=not getattr(args, "no_test_messages", False),
        response_wait_seconds=getattr(args, "response_wait", 5.0),
        prioritize_unread=getattr(args, "prioritize_unread", False),
        unread_only=getattr(args, "unread_only", False),
        resume=getattr(args, "resume", False),
        timing_multiplier=getattr(args, "timing_multiplier", 1.0),
        interactive_wait_timeout=getattr(args, "wait_timeout", 40.0),
        max_interaction_rounds=getattr(args, "max_rounds", 10),
        dynamic_unread_detection=getattr(args, "dynamic_unread", True),
    )


def options_from_dict(data: dict[str, Any]) -> SyncOptions:
    """
    从字典创建同步选项

    Args:
        data: 配置字典

    Returns:
        SyncOptions 实例
    """
    return SyncOptions(
        send_test_messages=data.get("send_test_messages", True),
        response_wait_seconds=data.get("response_wait_seconds", 5.0),
        prioritize_unread=data.get("prioritize_unread", False),
        unread_only=data.get("unread_only", False),
        resume=data.get("resume", False),
        timing_multiplier=data.get("timing_multiplier", 1.0),
        interactive_wait_timeout=data.get("interactive_wait_timeout", 40.0),
        max_interaction_rounds=data.get("max_interaction_rounds", 10),
        dynamic_unread_detection=data.get("dynamic_unread_detection", True),
    )


def options_to_dict(options: SyncOptions) -> dict[str, Any]:
    """
    将同步选项转换为字典

    Args:
        options: SyncOptions 实例

    Returns:
        配置字典
    """
    return {
        "send_test_messages": options.send_test_messages,
        "response_wait_seconds": options.response_wait_seconds,
        "prioritize_unread": options.prioritize_unread,
        "unread_only": options.unread_only,
        "resume": options.resume,
        "timing_multiplier": options.timing_multiplier,
        "interactive_wait_timeout": options.interactive_wait_timeout,
        "max_interaction_rounds": options.max_interaction_rounds,
        "dynamic_unread_detection": options.dynamic_unread_detection,
    }
