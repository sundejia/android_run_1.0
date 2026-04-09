"""
同步模块 - 负责全量同步的核心逻辑

模块组成:
- orchestrator: 同步编排器，协调整个同步流程
- customer_syncer: 客户同步器，处理单个客户的同步
- checkpoint: 断点管理器，支持断点续传
- options: 同步选项配置
- factory: 同步服务工厂，便捷创建组件
"""

from wecom_automation.services.sync.checkpoint import CheckpointManager
from wecom_automation.services.sync.customer_syncer import CustomerSyncer
from wecom_automation.services.sync.factory import create_customer_syncer, create_sync_orchestrator
from wecom_automation.services.sync.options import SyncOptions, create_sync_options, options_from_args
from wecom_automation.services.sync.orchestrator import SyncOrchestrator

__all__ = [
    # 配置
    "SyncOptions",
    "create_sync_options",
    "options_from_args",
    # 核心组件
    "SyncOrchestrator",
    "CustomerSyncer",
    "CheckpointManager",
    # 工厂方法
    "create_sync_orchestrator",
    "create_customer_syncer",
]
