# Follow-up Service 重构升级计划

## 1. 背景

### 1.1 当前问题

`followup_service.py` 文件存在以下问题：

| 问题     | 描述                                                  |
| -------- | ----------------------------------------------------- |
| 文件过长 | 2447 行代码，包含 44 个方法                           |
| 职责过多 | 数据库操作、AI 回复、设备扫描、后台调度等功能混在一起 |
| 代码重复 | 与全量同步模块存在大量重复代码                        |
| 难以维护 | 单一文件修改风险大，测试困难                          |

### 1.2 重复代码分析

| 重复功能       | followup_service 位置                          | 已有实现                                          |
| -------------- | ---------------------------------------------- | ------------------------------------------------- |
| 消息发送者判断 | `_is_message_from_kefu()` (1394-1567行)        | `UIParserService.determine_message_sender()`      |
| 屏幕宽度检测   | `_detect_screen_width()` (1374-1392行)         | `UIParserService._detect_screen_width()`          |
| 节点边界获取   | `_get_node_bounds()` (1569-1582行)             | `UIParserService._get_node_bounds()`              |
| AI 回复生成    | `_generate_reply_for_response()` (1679-1820行) | `AIReplyService.get_reply()`                      |
| 客户查找/创建  | `find_or_create_customer()` (444-487行)        | `ConversationRepository.get_or_create_customer()` |

---

## 2. 重构目标

### 2.1 设计原则

- **单一职责原则 (SRP)**: 每个类只负责一个功能领域
- **开闭原则 (OCP)**: 对扩展开放，对修改关闭
- **依赖倒置原则 (DIP)**: 依赖抽象而非具体实现
- **DRY 原则**: 复用全量同步中已有的组件

### 2.2 目标架构

```
wecom-desktop/backend/servic../03-impl-and-arch/
├── __init__.py              # 模块导出
├── models.py                # 数据模型 (FollowUpCandidate, ScanResult 等)
├── settings.py              # 设置管理 (FollowUpSettings)
├── repository.py            # 数据库操作 (FollowUpRepository)
├── scanner.py               # 设备扫描逻辑 (FollowUpScanner)
├── scheduler.py             # 后台调度器 (BackgroundScheduler)
├── response_detector.py     # 回复检测 (ResponseDetector)
└── service.py               # 主服务入口 (FollowUpService) - 精简版
```

---

## 3. 模块划分

### 3.1 models.py - 数据模型

**职责**: 定义 Follow-up 系统的数据结构

```python
# 从原文件提取并精简
@dataclass
class FollowUpCandidate:
    """需要跟进的客户"""
    customer_id: int
    customer_name: str
    channel: Optional[str]
    kefu_id: int
    last_kefu_message_time: datetime
    last_customer_message_time: Optional[datetime]
    previous_attempts: int
    seconds_since_last_kefu_message: int
    required_delay: int
    is_ready: bool

@dataclass
class ScanResult:
    """扫描结果"""
    scan_time: datetime
    candidates_found: int
    followups_sent: int
    followups_failed: int
    errors: List[str]
    details: List[Dict[str, Any]]

@dataclass
class FollowUpAttempt:
    """跟进尝试记录"""
    id: int
    customer_id: int
    attempt_number: int
    status: str
    message_content: str
    responded: bool
    created_at: datetime
```

**行数**: ~80 行

---

### 3.2 settings.py - 设置管理

**职责**: 管理 Follow-up 系统配置

```python
@dataclass
class FollowUpSettings:
    """跟进设置"""
    enabled: bool = True
    scan_interval: int = 60
    max_followups: int = 3
    initial_delay: int = 120
    subsequent_delay: int = 120
    use_exponential_backoff: bool = False
    backoff_multiplier: float = 2.0
    enable_operating_hours: bool = True
    start_hour: int = 10
    end_hour: int = 22
    use_ai_reply: bool = False

class SettingsManager:
    """设置管理器"""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def get_settings(self) -> FollowUpSettings:
        """获取设置"""
        ...

    def save_settings(self, settings: FollowUpSettings) -> None:
        """保存设置"""
        ...

    def is_within_operating_hours(self) -> bool:
        """检查是否在工作时间内"""
        ...

    def calculate_required_delay(self, attempt_number: int) -> int:
        """计算所需延迟时间"""
        ...
```

**行数**: ~120 行
**复用**: 无（设置逻辑是 Follow-up 特有的）

---

### 3.3 repository.py - 数据库操作

**职责**: Follow-up 相关的数据库操作

```python
class FollowUpRepository:
    """Follow-up 数据仓库"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_tables()

    # 基础操作
    def _init_tables(self) -> None:
        """初始化数据库表"""
        ...

    # 跟进记录操作
    def record_attempt(self, attempt: FollowUpAttempt) -> int:
        """记录跟进尝试"""
        ...

    def mark_responded(self, customer_id: int) -> int:
        """标记客户已回复"""
        ...

    def get_attempt_count(self, customer_id: int) -> int:
        """获取跟进尝试次数"""
        ...

    # 候选客户查询
    def find_candidates(self, settings: FollowUpSettings) -> List[FollowUpCandidate]:
        """查找需要跟进的客户"""
        ...

    def get_pending_customers(self) -> List[Dict[str, Any]]:
        """获取待回复的客户"""
        ...
```

**行数**: ~200 行
**复用**:

- 可选择复用 `ConversationRepository` 的连接管理
- 客户创建可调用 `ConversationRepository.get_or_create_customer()`

---

### 3.4 scanner.py - 设备扫描器

**职责**: 执行单设备/多设备的跟进扫描

```python
class FollowUpScanner:
    """Follow-up 设备扫描器"""

    def __init__(
        self,
        repository: FollowUpRepository,
        settings_manager: SettingsManager,
        ai_service: Optional[IAIReplyService] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._repository = repository
        self._settings = settings_manager
        self._ai_service = ai_service
        self._logger = logger
        self._cancel_requested = False

    async def scan_device(
        self,
        device_serial: str,
        exclude_users: List[str] = None,
        target_users: List[str] = None,
    ) -> ScanResult:
        """扫描单个设备"""
        # 复用 WeComService 进行设备操作
        wecom = WeComService(Config(device_serial=device_serial))
        ...

    async def scan_all_devices(
        self,
        exclude_users: List[str] = None,
        target_users: List[str] = None,
    ) -> ScanResult:
        """并行扫描所有设备"""
        ...

    async def _process_user(
        self,
        wecom: WeComService,
        user_name: str,
        user_channel: str,
    ) -> Dict[str, Any]:
        """处理单个用户"""
        # 复用 ui_parser.extract_conversation_messages()
        # 复用 ui_parser.determine_message_sender() 替代 _is_message_from_kefu()
        ...

    def request_cancel(self) -> None:
        """请求取消扫描"""
        self._cancel_requested = True
```

**行数**: ~400 行
**复用**:

- `WeComService` - 设备控制
- `UIParserService.extract_conversation_messages()` - 消息提取
- `UIParserService.determine_message_sender()` - 消息发送者判断 ⚠️ **替代重复代码**
- `UIParserService._detect_screen_width()` - 屏幕宽度检测 ⚠️ **替代重复代码**

---

### 3.5 response_detector.py - 回复检测器

**职责**: 检测客户回复并处理

```python
class ResponseDetector:
    """客户回复检测器"""

    def __init__(
        self,
        repository: FollowUpRepository,
        ai_service: Optional[IAIReplyService] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._repository = repository
        self._ai_service = ai_service
        self._logger = logger

    async def detect_and_reply(
        self,
        device_serial: Optional[str] = None,
    ) -> Dict[str, Any]:
        """检测回复并自动回复"""
        # 复用 WeComService
        # 复用 AIReplyService.get_reply() 替代 _generate_reply_for_response()
        ...

    async def _generate_reply(
        self,
        messages: List[Any],
        customer_name: str,
    ) -> Optional[str]:
        """生成 AI 回复"""
        # 直接使用 AIReplyService
        if self._ai_service:
            return await self._ai_service.get_reply(...)
        return None
```

**行数**: ~250 行
**复用**:

- `AIReplyService.get_reply()` - AI 回复生成 ⚠️ **替代重复代码**
- `WeComService` - 设备控制

---

### 3.6 scheduler.py - 后台调度器

**职责**: 管理后台扫描任务

```python
class BackgroundScheduler:
    """后台扫描调度器"""

    def __init__(
        self,
        scanner: FollowUpScanner,
        response_detector: ResponseDetector,
        settings_manager: SettingsManager,
        logger: Optional[logging.Logger] = None,
    ):
        self._scanner = scanner
        self._detector = response_detector
        self._settings = settings_manager
        self._logger = logger

        self._running = False
        self._paused = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动后台扫描"""
        ...

    async def stop(self) -> None:
        """停止后台扫描"""
        ...

    async def pause_for_sync(self) -> Dict[str, Any]:
        """暂停（用于全量同步）"""
        ...

    async def resume_after_sync(self) -> Dict[str, Any]:
        """恢复"""
        ...

    def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        ...

    async def _scan_loop(self) -> None:
        """扫描循环"""
        while self._running:
            # Phase 1: 检测回复
            # Phase 2: 发送跟进
            ...
```

**行数**: ~200 行
**复用**: 无（调度逻辑是 Follow-up 特有的）

---

### 3.7 service.py - 主服务入口

**职责**: 组装各组件，提供统一接口

```python
class FollowUpService:
    """Follow-up 服务 (精简版)"""

    def __init__(self, db_path: str = "wecom_conversations.db"):
        # 初始化各组件
        self._settings = SettingsManager(db_path)
        self._repository = FollowUpRepository(db_path)
        self._ai_service = None  # 懒加载
        self._scanner = None     # 懒加载
        self._detector = None    # 懒加载
        self._scheduler = None   # 懒加载

        # 日志系统
        self._log_callbacks = []
        self._log_history = []

    # === 设置 ===
    def get_settings(self) -> FollowUpSettings:
        return self._settings.get_settings()

    def save_settings(self, settings: FollowUpSettings) -> None:
        self._settings.save_settings(settings)

    # === 扫描 ===
    async def run_scan(self) -> ScanResult:
        return await self._get_scanner().scan_all_devices()

    async def scan_for_responses(self) -> Dict[str, Any]:
        return await self._get_detector().detect_and_reply()

    # === 后台调度 ===
    async def start_background_scanner(self) -> None:
        await self._get_scheduler().start()

    async def stop_background_scanner(self) -> None:
        await self._get_scheduler().stop()

    # === 日志 ===
    def register_log_callback(self, callback) -> None:
        ...

    def get_log_history(self) -> List[Dict]:
        ...

    # === 懒加载辅助 ===
    def _get_scanner(self) -> FollowUpScanner:
        if not self._scanner:
            self._scanner = FollowUpScanner(...)
        return self._scanner
```

**行数**: ~150 行
**复用**: 组合其他模块

---

## 4. 复用策略

### 4.1 直接复用的组件

| 组件                     | 来源                                         | 用途              |
| ------------------------ | -------------------------------------------- | ----------------- |
| `WeComService`           | `wecom_automation.services.wecom_service`    | 设备控制          |
| `UIParserService`        | `wecom_automation.services.ui_parser`        | UI 解析、消息提取 |
| `AIReplyService`         | `wecom_automation.services.ai.reply_service` | AI 回复生成       |
| `ConversationRepository` | `wecom_automation.database.repository`       | 客户数据操作      |
| `Config`                 | `wecom_automation.core.config`               | 配置管理          |

### 4.2 需要删除的重复代码

| 方法                             | 行数    | 替代方案                                     |
| -------------------------------- | ------- | -------------------------------------------- |
| `_is_message_from_kefu()`        | ~170 行 | `UIParserService.determine_message_sender()` |
| `_detect_screen_width()`         | ~18 行  | `UIParserService._detect_screen_width()`     |
| `_get_node_bounds()`             | ~14 行  | `UIParserService._get_node_bounds()`         |
| `_generate_reply_for_response()` | ~140 行 | `AIReplyService.get_reply()`                 |

**总计可删除**: ~342 行重复代码

### 4.3 需要调整的复用接口

为了让 `followup` 模块能复用 `UIParserService` 的方法，需要：

1. **将 `determine_message_sender()` 设为公开方法**
   - 当前可能是内部方法
   - 需要确保接口稳定

2. **将 `_detect_screen_width()` 设为公开方法**
   - 改名为 `detect_screen_width()` 或提供静态方法

---

## 5. 实施计划

### Phase 1: 准备工作 (0.5 天)

- [ ] 创建 `wecom-desktop/backend/servic../03-impl-and-arch/` 目录
- [ ] 创建 `__init__.py`
- [ ] 确保 `UIParserService` 的复用接口可用

### Phase 2: 提取数据模型 (0.5 天)

- [ ] 创建 `models.py`
- [ ] 从原文件提取 `FollowUpCandidate`, `ScanResult` 等
- [ ] 添加类型注解和文档

### Phase 3: 提取设置管理 (0.5 天)

- [ ] 创建 `settings.py`
- [ ] 提取 `get_settings()`, `calculate_required_delay()` 等
- [ ] 单元测试

### Phase 4: 提取数据仓库 (1 天)

- [ ] 创建 `repository.py`
- [ ] 提取数据库操作方法
- [ ] 复用 `ConversationRepository` 的客户操作
- [ ] 单元测试

### Phase 5: 提取扫描器 (1.5 天)

- [ ] 创建 `scanner.py`
- [ ] 提取 `run_active_scan_for_device()`, `run_multi_device_scan()`
- [ ] **删除重复的 `_is_message_from_kefu()`，改用 `UIParserService`**
- [ ] 集成测试

### Phase 6: 提取回复检测器 (1 天)

- [ ] 创建 `response_detector.py`
- [ ] 提取 `scan_for_responses()`
- [ ] **删除重复的 `_generate_reply_for_response()`，改用 `AIReplyService`**
- [ ] 集成测试

### Phase 7: 提取调度器 (0.5 天)

- [ ] 创建 `scheduler.py`
- [ ] 提取后台扫描相关逻辑
- [ ] 集成测试

### Phase 8: 重构主服务 (0.5 天)

- [ ] 创建精简版 `service.py`
- [ ] 组装各组件
- [ ] 确保 API 兼容性

### Phase 9: 更新路由 (0.5 天)

- [ ] 更新 `followup.py` 路由，使用新的模块结构
- [ ] 端到端测试

### Phase 10: 清理和文档 (0.5 天)

- [ ] 删除旧的 `followup_service.py`
- [ ] 更新文档
- [ ] 代码审查

---

## 6. 预期收益

### 6.1 代码量对比

| 项目       | 重构前  | 重构后   |
| ---------- | ------- | -------- |
| 总行数     | 2447 行 | ~1400 行 |
| 最大单文件 | 2447 行 | ~400 行  |
| 重复代码   | ~342 行 | 0 行     |
| 文件数量   | 1 个    | 7 个     |

### 6.2 质量提升

- **可维护性**: 每个文件职责明确，易于理解和修改
- **可测试性**: 各模块可独立测试
- **可复用性**: 复用全量同步的成熟代码
- **一致性**: 统一使用 `UIParserService` 和 `AIReplyService`

---

## 7. 风险与缓解

| 风险           | 缓解措施                            |
| -------------- | ----------------------------------- |
| API 不兼容     | 保持 `FollowUpService` 对外接口不变 |
| 复用组件有 bug | 先在全量同步中修复，再复用          |
| 重构引入新 bug | 保留旧文件作为参考，逐步迁移        |
| 性能下降       | 懒加载组件，按需初始化              |

---

## 8. 文件结构预览

```
wecom-desktop/
└── backend/
    └── services/
        └── followup/                    # 新增目录
            ├── __init__.py              # ~30 行
            ├── models.py                # ~80 行
            ├── settings.py              # ~120 行
            ├── repository.py            # ~200 行
            ├── scanner.py               # ~400 行
            ├── response_detector.py     # ~250 行
            ├── scheduler.py             # ~200 行
            └── service.py               # ~150 行
                                         # 总计 ~1430 行

src/wecom_automation/services/         # 已有模块 (复用)
├── wecom_service.py                   # 设备控制
├── ui_parser.py                       # UI 解析
└── ai/
    └── reply_service.py               # AI 回复
```

---

## 9. 版本控制

| 版本 | 日期    | 更新内容     |
| ---- | ------- | ------------ |
| 1.0  | 2025-01 | 初始升级计划 |
| 1.1  | 2025-01 | 完成重构实施 |

---

## 10. 实施完成总结

### 已创建的文件

| 文件                            | 行数      | 说明         |
| ------------------------------- | --------- | ------------ |
| `followup/__init__.py`          | 40        | 模块导出     |
| `followup/models.py`            | 60        | 数据模型定义 |
| `followup/settings.py`          | 200       | 设置管理器   |
| `followup/repository.py`        | 280       | 数据库操作   |
| `followup/scanner.py`           | 420       | 设备扫描器   |
| `followup/response_detector.py` | 340       | 回复检测器   |
| `followup/scheduler.py`         | 200       | 后台调度器   |
| `followup/service.py`           | 280       | 主服务入口   |
| **总计**                        | **~1820** |              |

### 兼容性处理

- `followup_service.py` → 保留为兼容层，重定向到新模块
- `followup_service_backup.py` → 原始代码备份

### 复用组件

| 组件                                              | 用途               |
| ------------------------------------------------- | ------------------ |
| `WeComService`                                    | 设备控制、消息发送 |
| `UIParserService.extract_conversation_messages()` | 消息提取           |
| `UIParserService.determine_message_sender()`      | 消息发送者判断     |
| `UnreadUserExtractor`                             | 未读用户提取       |
| `Config, ScrollConfig`                            | 配置管理           |

### 删除的重复代码

| 方法                             | 说明                   |
| -------------------------------- | ---------------------- |
| `_is_message_from_kefu()`        | 改用 `UIParserService` |
| `_detect_screen_width()`         | 改用 `UIParserService` |
| `_get_node_bounds()`             | 改用 `UIParserService` |
| `_generate_reply_for_response()` | 简化为直接调用 AI API  |
