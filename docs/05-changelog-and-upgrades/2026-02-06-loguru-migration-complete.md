# Loguru 日志系统迁移完成

**日期**: 2026-02-06  
**影响范围**: 整个项目  
**状态**: ✅ 完成

---

## 📋 概述

成功将项目的日志系统从 `stdlib logging` 迁移到 `loguru`，统一了整个项目的日志配置，简化了日志管理，提高了可维护性。

---

## ✅ 完成的阶段

### Phase 1: Core Logging Migration ✅

- ✅ 重写 `src/wecom_automation/core/logging.py` 为基于 `loguru` 的实现
- ✅ 实现 `init_logging()` - 全局控制台和 `global.log` 文件 sink
- ✅ 实现 `add_device_sink()` - 设备特定的 `hostname-{serial}.log` 文件
- ✅ 实现 `remove_device_sink()` - 清理设备 sink
- ✅ 实现 `get_logger()` - 绑定模块和设备上下文
- ✅ 保留 `setup_logger()` 用于向后兼容
- ✅ 适配 `log_operation()` 装饰器
- ✅ 删除 `src/wecom_automation/core/log_config.py`（已过时）
- ✅ 删除 `wecom-desktop/backend/services/followup/log_config.py`（冗余）

### Phase 2: Backend Main Service Migration ✅

- ✅ 更新 `wecom-desktop/backend/main.py`
  - 移除 `logging` 和 `TimedRotatingFileHandler` 导入
  - 重写 `setup_backend_logging()` 使用 `init_logging()`
  - 添加 `_get_hostname()` 以获取一致的主机名
  - 更新 `ensure_directories()` 以创建 `logs` 和 `logs/metrics`
  - 在 `lifespan()` 中调用 `setup_backend_logging()`
  - 添加 `sys.path` 清理逻辑以防止虚拟环境冲突

### Phase 3: Subprocess Scripts Migration ✅

- ✅ 更新 `wecom-desktop/backend/scripts/realtime_reply_process.py`
  - 移除 `logging` 导入和 stdlib 日志设置
  - 重写 `setup_logging()` 使用 `loguru.init_logging`
  - 添加手动 `sys.stdout` sink 以兼容前端日志面板
  - 修复导入顺序以防止 `ModuleNotFoundError`
  - 修复 `cleanup_skip_flag()` 中的 `logging` 未定义错误
  - 修复 Sidecar 客户端传递逻辑

- ✅ 更新 `wecom-desktop/backend/scripts/initial_sync.py`
  - 移除 `logging` 导入和 stdlib 日志设置
  - 重写 `setup_logging()` 使用 `loguru.init_logging`
  - 添加手动 `sys.stdout` sink 以兼容前端日志面板
  - 修改 `run()` 函数提前初始化 `Config`

### Phase 4: Response Detector Migration ✅

- ✅ 更新 `wecom-desktop/backend/services/followup/response_detector.py`
  - 移除 `logging` 导入和 `TimedRotatingFileHandler`
  - 移除 `_setup_response_detector_logging()` 函数
  - 使用 `get_logger()` 创建 `_logger` 和 `_message_tracker_logger`
  - 为 `_message_tracker_logger` 绑定设备上下文
  - 添加 `sidecar_client` 参数以支持依赖注入
  - 修复优先级逻辑以尊重提供的 `sidecar_client`

### Phase 5: Legacy Service Migration ✅

- ✅ 更新 `wecom-desktop/backend/services/followup/service.py`
  - 添加 `import logging`（用于向后兼容）
  - 标记为 `(LEGACY)` 和 `DEPRECATED`
  - 修改 `_EnhancedLogHandler._setup_file_handler` 使用新的 `logs/` 目录
  - 将日志文件名更改为 `followup-service-legacy.log`，7 天保留

### Phase 6: Metrics Logger Migration ✅

- ✅ 重构 `src/wecom_automation/core/metrics_logger.py`
  - 用 `loguru.logger` 替换 `stdlib logging`
  - 使用 `_loguru_logger.add()` 创建设备特定的 JSON Lines sink
  - 文件名格式: `{hostname}-{serial}.jsonl`
  - 添加 `filter` 和 `bind` 以进行上下文隔离
  - 更新 `get_metrics_logger` 接受可选的 `hostname` 参数
  - 添加 `_get_hostname()` 从设置中检索主机名

### Phase 7: Legacy Service Logging Migration ✅

- ✅ 更新 `wecom-desktop/backend/services/followup/service.py`
  - 移除 `_EnhancedLogHandler` 类（基于 `logging.Handler`）
  - 实现 `_setup_loguru_sinks()` 方法
  - 添加文件 sink (`followup-service-legacy.log`, 7 天保留)
  - 添加自定义 sink 用于前端日志转发
  - 更新 `__del__` 清理 loguru sinks
- ✅ 更新 `src/wecom_automation/services/integration/sidecar.py`
  - 类型提示从 `logging.Logger` 改为 `Any`
  - 支持 loguru 和 stdlib logging
  - 默认使用 `get_logger()` 获取 loguru logger

### Phase 8: Printf-Style Formatting Fix ✅

- ✅ 更新 `src/wecom_automation/services/device_service.py`
  - 将所有 `logger.info("msg %s", var)` 调用替换为 `logger.info("msg {}", var)`
  - 确保与 `loguru` 的 `{}` 占位符语法兼容

### Phase 9: Dependency and Export Updates ✅

- ✅ 在 `pyproject.toml` 中添加 `loguru>=0.7.0`
- ✅ 更新 `src/wecom_automation/core/__init__.py` 的 `__all__` 和导入

---

## 🛠️ 重构成果

### 文件统计

**之前**:

- 5 个独立的日志配置文件
- 7+ 个日志文件/设备（分散在多个目录中）
- 多个 `TimedRotatingFileHandler` 实例
- 不一致的格式和目录结构

**之后**:

- 1 个统一的日志模块 (`core/logging.py`)
- 2 个日志文件/设备:
  - `logs/hostname-{serial}.log` (常规日志)
  - `logs/metrics/hostname-{serial}.jsonl` (业务指标)
- 1 个全局日志: `logs/global.log` (跨设备事件)
- 一致的格式和平面目录结构

### 新架构

```
┌─────────────────────────────────────────────────────────────┐
│ wecom_automation.core.logging (loguru)                      │
│ • init_logging()         - 全局控制台 + global.log           │
│ • add_device_sink()      - 添加 hostname-{serial}.log        │
│ • remove_device_sink()   - 清理设备 sink                      │
│ • get_logger()           - 绑定模块 + 设备上下文              │
│ • log_operation()        - 装饰器用于操作日志                │
└─────────────────────────────────────────────────────────────┘
         ▲                           ▲
         │                           │
         │                           │
┌────────┴─────────┐      ┌──────────┴────────────┐
│ backend/main.py  │      │ backend/scripts/      │
│ • init_logging() │      │ • init_logging()      │
│ • add_device_    │      │ • sys.stdout sink     │
│   sink()         │      │   (前端日志面板)        │
└──────────────────┘      └───────────────────────┘
```

### 日志格式

```
2026-02-06 14:32:26.123 | INFO     | wecom_automation.services.wecom_service:extract_conversation:456 | [AN2FVB1706003302] Extracting conversation...
```

### 日志文件命名

```
logs/
├── global.log                           # 全局日志（跨设备）
├── DESKTOP-ABC123-AN2FVB1706003302.log  # 设备特定日志
├── DESKTOP-ABC123-XYZ456.log            # 另一个设备
└── metrics/
    ├── DESKTOP-ABC123-AN2FVB1706003302.jsonl  # 设备指标
    └── DESKTOP-ABC123-XYZ456.jsonl            # 另一个设备指标
```

---

## 🐛 修复的问题

### 1. 虚拟环境路径冲突

**问题**: `ImportError: cannot import name 'init_logging'` 由于 venv 指向错误的项目目录  
**修复**: 在 `main.py` 中添加 `sys.path` 清理逻辑

### 2. 子进程导入顺序

**问题**: `ModuleNotFoundError: No module named 'utils'` 在 `realtime_reply_process.py` 中  
**修复**: 重新排序导入以在模块导入之前配置 `sys.path`

### 3. 遗留的 `logging` 调用

**问题**: `NameError: name 'logging' is not defined` 在多个文件中  
**修复**:

- `realtime_reply_process.py`: 从 `cleanup_skip_flag()` 中删除 `logging.getLogger()`
- `service.py`: 添加 `import logging` 以实现向后兼容

### 4. 日志目录不匹配

**问题**: 旧代码创建 `logs/backend/`, `logs/followup/`  
**修复**: 将 `ensure_directories()` 更新为仅创建 `logs/` 和 `logs/metrics/`

### 5. Sidecar 客户端优先级

**问题**: 命令行参数被数据库设置覆盖  
**修复**:

- 向 `detect_and_reply()` 添加 `sidecar_client` 参数
- 优先考虑提供的客户端而不是内部创建
- 在 `realtime_reply_process.py` 中传递客户端

### 6. Legacy Service addHandler 错误

**问题**: `'Logger' object has no attribute 'addHandler'` 在 `service.py` 中  
**修复**:

- 移除 `_EnhancedLogHandler` 类（基于 `logging.Handler`）
- 使用 loguru 的 `logger.add()` 添加自定义 sinks
- 文件 sink 用于日志持久化（`followup-service-legacy.log`）
- 自定义 sink 用于前端 WebSocket 转发
- `SidecarQueueClient` 支持 loguru 和 stdlib logging

### 7. Sidecar UnboundLocalError

**问题**: `cannot access local variable 'sidecar_client' where it is not associated with a value` 在 `response_detector.py` 中  
**修复**:

- 在 `except` 块中添加 `sidecar_client = None` 确保变量总是被初始化
- 即使异常发生，后续代码也能安全使用 `sidecar_client` 变量
- 防御性编程：在异常处理中设置默认值

---

## 📚 创建的新文档

1. ✅ `docs/03-impl-and-arch/key-modules/logging-system-architecture.md`
   - `loguru` 日志系统详细架构
   - 日志流程图（Mermaid）
   - 格式规范和配置示例
   - 前端集成指南

2. ✅ `docs/03-impl-and-arch/key-modules/directory-structure-migration.md`
   - 旧目录结构 vs 新目录结构对比
   - 迁移步骤和配置验证

3. ✅ `docs/04-bugs-and-fixes/resolved/2026-02-06-sidecar-client-none-warning.md`
   - "Sidecar client is None" 警告修复详情
   - 根本原因分析（设计冲突/优先级混乱）
   - 三个代码修改和验证步骤

4. ✅ `docs/04-bugs-and-fixes/resolved/2026-02-06-sidecar-addhandler-error.md`
   - "'Logger' object has no attribute 'addHandler'" 错误修复
   - Loguru sink 机制详解
   - Legacy service 日志系统重构

5. ✅ `docs/04-bugs-and-fixes/resolved/2026-02-06-sidecar-unbound-variable-error.md`
   - "UnboundLocalError: cannot access local variable 'sidecar_client'" 错误修复
   - Python 变量作用域和异常处理
   - 防御性编程最佳实践

### 更新的现有文档

1. ✅ `CLAUDE.md` - 新增故障排除部分:
   - `sys.path` 冲突（虚拟环境问题）
   - `ModuleNotFoundError`（子进程脚本）
   - `NameError: name 'logging' is not defined`（`loguru` 迁移后）
   - `'Logger' object has no attribute 'addHandler'`（Loguru sink 迁移）
   - `UnboundLocalError` 异常处理变量初始化

---

## 🎯 关键改进

### 1. 简化配置

- 从 5 个配置文件减少到 1 个核心模块
- 统一的 `init_logging()` 初始化
- 自动设备 sink 管理

### 2. 一致性

- 所有日志使用相同的格式
- 一致的文件命名约定 (`hostname-{serial}.log`)
- 统一的上下文绑定（`module`, `device`）

### 3. 可维护性

- 单一真相来源（`core/logging.py`）
- 清晰的职责分离
- 易于调试和故障排除

### 4. 性能

- 高效的日志轮换（`loguru` 内置）
- 轻量级上下文绑定
- 最小的 I/O 开销

### 5. 前端集成

- 标准化 `stdout` 输出（子进程脚本）
- DeviceManager 中的结构化解析
- WebSocket 实时流式传输到前端日志面板

---

## 🔍 验证检查清单

- [x] 所有核心导入成功（`init_logging`, `add_device_sink`, `get_logger`）
- [x] `loguru` 正确安装
- [x] 后端启动时没有错误
- [x] 设备 sink 正确创建
- [x] 日志输出到正确的文件
- [x] 前端日志面板接收日志
- [x] 指标记录器工作正常
- [x] 子进程脚本输出捕获
- [x] Sidecar 客户端优先级正确
- [x] 没有遗留的 `logging` 调用

---

## 📝 未来计划

### 短期（已完成 ✅）

- ✅ 迁移所有核心模块到 `loguru`
- ✅ 统一所有日志配置
- ✅ 修复所有子进程脚本
- ✅ 清理旧日志文件和目录
- ✅ 更新文档

### 长期（可选）

- [ ] 添加日志聚合（如有需要）
- [ ] 实现日志分析仪表板
- [ ] 考虑远程日志（Sentry, CloudWatch）
- [ ] 添加日志存档策略
- [ ] 优化日志旋转策略

---

## 🙏 致谢

此迁移解决了项目中的多个长期日志问题:

- 消除了配置碎片化
- 简化了多设备日志
- 改进了故障排除工作流
- 为未来的日志增强奠定了基础

---

**迁移开始**: 2026-02-06  
**迁移完成**: 2026-02-06  
**总耗时**: ~4 小时  
**受影响文件**: 15+ 文件  
**删除的代码**: ~500 行  
**添加的代码**: ~300 行  
**净减少**: ~200 行

---

## 📌 快速参考

### 基本使用

```python
# 1. 初始化（在 main.py 或脚本中）
from wecom_automation.core.logging import init_logging
init_logging(console=True)

# 2. 为设备添加 sink（可选）
from wecom_automation.core.logging import add_device_sink
sink_id = add_device_sink(device_serial="AN2FVB1706003302")

# 3. 获取记录器
from wecom_automation.core.logging import get_logger
logger = get_logger(__name__, device="AN2FVB1706003302")

# 4. 记录日志
logger.info("Processing message for device {}", device_serial)
logger.warning("Failed to send message: {}", error)

# 5. 清理（可选）
from wecom_automation.core.logging import remove_device_sink
remove_device_sink(sink_id)
```

### 指标记录

```python
from wecom_automation.core.metrics_logger import get_metrics_logger

metrics = get_metrics_logger(device_serial="AN2FVB1706003302")
metrics.log_message_sent(
    conversation_id="conv_123",
    message_type="text",
    success=True,
    duration_ms=150
)
```

### 操作日志装饰器

```python
from wecom_automation.core.logging import log_operation

@log_operation("Extracting conversation")
async def extract_conversation(self, conversation_name: str):
    # 函数逻辑
    pass
```

---

**状态**: ✅ **完成且已验证**  
**文档**: ✅ **已更新**  
**生产就绪**: ✅ **是**
