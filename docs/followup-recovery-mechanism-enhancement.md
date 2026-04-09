# 补刀功能错误恢复机制增强计划

## 1. 背景分析

### 1.1 当前实现状态

补刀功能通过搜索框进行操作，核心流程如下：

```
主页面 → 点击搜索 → 输入用户名 → 点击结果 → 发送消息 → 返回主页面
```

**现有错误处理机制**：

- 基本的异常捕获和日志记录
- `_safe_go_back()` 方法：固定按3次返回键尝试返回主页面
- 每个步骤都有 try-catch 包装

**存在的问题**：

1. **状态盲区**：无法确定当前处于哪个页面（搜索页/聊天页/其他）
2. **盲目返回**：固定按3次返回键，可能：
   - 不足：未能返回主页面
   - 过度：退出到系统桌面
   - 无效：在弹窗或对话框中无效
3. **缺乏验证**：返回后不验证是否真的到达主页面
4. **上下文丢失**：错误发生时未记录详细状态，难以分析根因
5. **无法恢复**：错误后只能标记失败，无法从中断点继续

### 1.2 影响范围

这些问题导致：

- 用户体验差：补刀失败率高，需要手动介入
- 效率低下：失败后无法自动重试，浪费时间
- 难以调试：缺乏状态信息，问题难以复现和定位
- 资源浪费：部分失败是暂时的，本可以通过重试解决

## 2. 增强目标

### 2.1 核心目标

1. **智能状态识别**：实时识别当前页面状态
2. **精准恢复策略**：根据状态选择最优返回路径
3. **恢复验证机制**：确保恢复到安全状态
4. **可重试性**：支持失败后智能重试
5. **可观测性**：详细的日志和状态追踪

### 2.2 非功能性目标

- **可靠性**：错误恢复成功率 > 95%
- **性能**：状态检测延迟 < 500ms
- **兼容性**：适配不同屏幕尺寸和微信版本
- **可维护性**：清晰的代码结构和文档

## 3. 详细设计方案

### 3.1 页面状态识别系统

#### 3.1.1 状态枚举定义

```python
from enum import Enum

class PageState(Enum):
    """补刀操作中的页面状态"""
    HOME = "home"                    # 主页面（消息列表）
    SEARCH_PAGE = "search_page"      # 搜索页面
    SEARCH_RESULT = "search_result"  # 搜索结果页
    CHAT_PAGE = "chat_page"          # 聊天页面
    KEYBOARD_UP = "keyboard_up"      # 键盘弹起状态
    DIALOG_OR_POPUP = "dialog"       # 弹窗或对话框
    UNKNOWN = "unknown"              # 未知状态
    SYSTEM_HOME = "system_home"      # 系统桌面（过度返回）
```

#### 3.1.2 状态检测器实现

```python
class PageStateDetector:
    """页面状态检测器"""

    def __init__(self, adb_service: ADBService):
        self.adb = adb_service
        self.ui_tree_cache = None

    async def detect_current_state(self, refresh: bool = True) -> PageState:
        """
        检测当前页面状态

        Args:
            refresh: 是否刷新UI树

        Returns:
            PageState: 当前页面状态
        """
        if refresh:
            self.ui_tree_cache = await self.adb.get_ui_tree()

        ui_tree = self.ui_tree_cache
        clickable_elements = await self.adb.get_clickable_elements()

        # 1. 检查是否在系统桌面（过度返回）
        if self._is_system_home(ui_tree):
            return PageState.SYSTEM_HOME

        # 2. 检查是否有弹窗
        if self._has_dialog(ui_tree, clickable_elements):
            return PageState.DIALOG_OR_POPUP

        # 3. 检查键盘是否弹起
        if self._is_keyboard_up(ui_tree):
            return PageState.KEYBOARD_UP

        # 4. 检查是否在聊天页面
        if self._is_chat_page(ui_tree, clickable_elements):
            return PageState.CHAT_PAGE

        # 5. 检查是否在搜索结果页
        if self._is_search_result(ui_tree):
            return PageState.SEARCH_RESULT

        # 6. 检查是否在搜索页面
        if self._is_search_page(ui_tree, clickable_elements):
            return PageState.SEARCH_PAGE

        # 7. 检查是否在主页面（消息列表）
        if self._is_home_page(ui_tree, clickable_elements):
            return PageState.HOME

        return PageState.UNKNOWN

    def _is_system_home(self, ui_tree: dict) -> bool:
        """检测是否在系统桌面"""
        # 特征：缺少企业微信特有的元素，有系统桌面特征
        # 例如：没有消息列表、没有标题栏
        # 或者检测到系统应用图标
        pass

    def _has_dialog(self, ui_tree: dict, clickable_elements: list) -> bool:
        """检测是否有弹窗或对话框"""
        # 特征：
        # 1. 有"确定"、"取消"按钮
        # 2. 有模态遮罩（半透明背景）
        # 3. 弹窗容器在顶层
        pass

    def _is_keyboard_up(self, ui_tree: dict) -> bool:
        """检测键盘是否弹起"""
        # 特征：
        # 1. 输入框获得焦点
        # 2. 屏幕底部被遮挡（可用高度减少）
        # 3. 有键盘相关的布局
        pass

    def _is_chat_page(self, ui_tree: dict, clickable_elements: list) -> bool:
        """检测是否在聊天页面"""
        # 特征：
        # 1. 有聊天输入框（EditText）
        # 2. 有发送按钮
        # 3. 有消息列表元素
        # 4. 顶部有用户名
        pass

    def _is_search_result(self, ui_tree: dict) -> bool:
        """检测是否在搜索结果页"""
        # 特征：
        # 1. 有搜索关键词显示
        # 2. 有结果列表
        # 3. 有"联系人"、"群聊"、"聊天记录"等标签
        pass

    def _is_search_page(self, ui_tree: dict, clickable_elements: list) -> bool:
        """检测是否在搜索页面"""
        # 特征：
        # 1. 有搜索输入框
        # 2. 有搜索按钮
        # 3. 可能显示历史搜索记录
        pass

    def _is_home_page(self, ui_tree: dict, clickable_elements: list) -> bool:
        """检测是否在主页面（消息列表）"""
        # 特征：
        # 1. 有搜索按钮（resourceId: com.tencent.wework:id/ngq）
        # 2. 有会话列表
        # 3. 有"消息"、"通讯录"、"工作台"、"我"等底部导航
        pass
```

### 3.2 智能恢复策略

#### 3.2.1 恢复策略映射表

```python
class RecoveryStrategy:
    """恢复策略"""

    def __init__(self, adb_service: ADBService):
        self.adb = adb_service
        self.detector = PageStateDetector(adb_service)

    async def recover_to_home(self) -> bool:
        """
        从任意状态恢复到主页面

        Returns:
            bool: 是否成功恢复
        """
        max_attempts = 3

        for attempt in range(max_attempts):
            current_state = await self.detector.detect_current_state()
            self._log(f"当前状态: {current_state.value}", "INFO")

            if current_state == PageState.HOME:
                self._log("已处于主页面", "INFO")
                return True

            if current_state == PageState.UNKNOWN:
                self._log("未知状态，尝试通用恢复", "WARN")
                await self._generic_recovery()
                continue

            if current_state == PageState.SYSTEM_HOME:
                self._log("过度返回到系统桌面，重新打开企业微信", "WARN")
                await self._reopen_wecom()
                continue

            # 根据状态选择恢复策略
            success = await self._apply_strategy(current_state)
            if success:
                return True

        return False

    async def _apply_strategy(self, state: PageState) -> bool:
        """应用特定状态的恢复策略"""

        strategies = {
            PageState.DIALOG_OR_POPUP: self._recover_from_dialog,
            PageState.KEYBOARD_UP: self._recover_from_keyboard,
            PageState.CHAT_PAGE: self._recover_from_chat,
            PageState.SEARCH_RESULT: self._recover_from_search_result,
            PageState.SEARCH_PAGE: self._recover_from_search_page,
        }

        handler = strategies.get(state)
        if handler:
            return await handler()

        return False

    async def _recover_from_dialog(self) -> bool:
        """从弹窗状态恢复"""
        # 策略：
        # 1. 查找"取消"或"关闭"按钮并点击
        # 2. 如果找不到，尝试点击弹窗外部
        # 3. 如果仍无效，按返回键
        pass

    async def _recover_from_keyboard(self) -> bool:
        """从键盘弹起状态恢复"""
        # 策略：
        # 1. 点击输入框外部收起键盘
        # 2. 或按返回键收起键盘
        pass

    async def _recover_from_chat(self) -> bool:
        """从聊天页面恢复"""
        # 策略：
        # 1. 第1次返回：收起键盘（如果弹起）
        # 2. 第2次返回：退出聊天页
        # 3. 验证是否到达主页面
        pass

    async def _recover_from_search_result(self) -> bool:
        """从搜索结果页恢复"""
        # 策略：
        # 1. 清空搜索框
        # 2. 或按返回键退出搜索
        pass

    async def _recover_from_search_page(self) -> bool:
        """从搜索页面恢复"""
        # 策略：
        # 1. 清空搜索框（如果有内容）
        # 2. 按返回键退出搜索
        pass

    async def _generic_recovery(self) -> bool:
        """通用恢复策略（未知状态）"""
        # 策略：
        # 1. 连续按返回键（最多5次）
        # 2. 每次按后检测状态
        # 3. 到达主页面或检测到过度返回则停止
        pass

    async def _reopen_wecom(self) -> bool:
        """重新打开企业微信"""
        # 策略：
        # 1. 启动企业微信应用
        # 2. 等待加载完成
        # 3. 验证是否到达主页面
        pass
```

#### 3.2.2 恢复验证机制

```python
class RecoveryValidator:
    """恢复验证器"""

    def __init__(self, adb_service: ADBService):
        self.adb = adb_service
        self.detector = PageStateDetector(adb_service)

    async def validate_home_state(self) -> tuple[bool, str]:
        """
        验证是否处于主页面

        Returns:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        state = await self.detector.detect_current_state()

        if state == PageState.HOME:
            return True, "已成功返回主页面"

        if state == PageState.SYSTEM_HOME:
            return False, "过度返回到系统桌面"

        if state == PageState.UNKNOWN:
            return False, f"无法确定当前状态，UI树可能异常"

        return False, f"当前处于 {state.value} 状态，未返回主页面"

    async def ensure_home_state(self, max_retries: int = 3) -> bool:
        """
        确保处于主页面，自动尝试恢复

        Args:
            max_retries: 最大重试次数

        Returns:
            bool: 是否成功
        """
        for attempt in range(max_retries):
            is_home, message = await self.validate_home_state()

            if is_home:
                return True

            self._log(f"验证失败 (尝试 {attempt + 1}/{max_retries}): {message}", "WARN")

            # 尝试恢复
            strategy = RecoveryStrategy(self.adb)
            success = await strategy.recover_to_home()

            if not success:
                self._log("恢复失败", "ERROR")
                return False

        return False
```

### 3.3 上下文记录系统

#### 3.3.1 错误上下文快照

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class ErrorContext:
    """错误上下文快照"""
    timestamp: datetime = field(default_factory=datetime.now)
    current_step: str = ""                    # 当前执行步骤
    page_state: PageState = PageState.UNKNOWN # 页面状态
    ui_tree_hash: str = ""                    # UI树哈希值（用于调试）
    error_message: str = ""                   # 错误消息
    error_traceback: str = ""                 # 错误堆栈
    target_user: Optional[str] = None         # 目标用户
    message_to_send: Optional[str] = None     # 待发送消息
    execution_phase: str = ""                 # 执行阶段

    def to_dict(self) -> dict:
        """转换为字典（用于数据库存储或日志）"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "current_step": self.current_step,
            "page_state": self.page_state.value,
            "ui_tree_hash": self.ui_tree_hash,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "target_user": self.target_user,
            "message_to_send": self.message_to_send,
            "execution_phase": self.execution_phase,
        }

class ErrorContextManager:
    """错误上下文管理器"""

    def __init__(self, adb_service: ADBService, log_callback=None):
        self.adb = adb_service
        self.log_callback = log_callback
        self.current_context: Optional[ErrorContext] = None

    async def capture_context(
        self,
        step: str,
        error: Exception,
        target_user: Optional[str] = None,
        message: Optional[str] = None,
        phase: str = ""
    ) -> ErrorContext:
        """
        捕获错误上下文

        Args:
            step: 当前执行步骤
            error: 异常对象
            target_user: 目标用户
            message: 待发送消息
            phase: 执行阶段

        Returns:
            ErrorContext: 错误上下文快照
        """
        detector = PageStateDetector(self.adb)

        context = ErrorContext(
            current_step=step,
            page_state=await detector.detect_current_state(),
            error_message=str(error),
            error_traceback=traceback.format_exc(),
            target_user=target_user,
            message_to_send=message,
            execution_phase=phase
        )

        # 计算UI树哈希
        ui_tree = await self.adb.get_ui_tree()
        context.ui_tree_hash = hashlib.md5(str(ui_tree).encode()).hexdigest()[:8]

        self.current_context = context
        self._log_context(context)

        return context

    def _log_context(self, context: ErrorContext):
        """记录错误上下文"""
        log_msg = f"""
========== 错误上下文快照 ==========
时间: {context.timestamp}
步骤: {context.current_step}
状态: {context.page_state.value}
UI树哈希: {context.ui_tree_hash}
错误: {context.error_message}
目标用户: {context.target_user or 'N/A'}
执行阶段: {context.execution_phase or 'N/A'}
====================================
"""
        if self.log_callback:
            self.log_callback(log_msg, "ERROR")
        else:
            print(log_msg)
```

### 3.4 智能重试机制

#### 3.4.1 重试决策器

```python
class RetryDecision:
    """重试决策"""

    def __init__(self):
        # 可重试的错误类型
        self.retryable_errors = {
            "元素未找到": True,
            "UI树解析超时": True,
            "搜索结果为空": True,
            "网络连接失败": True,
        }

        # 不可重试的错误类型
        self.non_retryable_errors = {
            "用户不存在": False,
            "已删除好友": False,
            "被拉黑": False,
            "数据库错误": False,
        }

    def should_retry(self, error_context: ErrorContext, attempt: int) -> bool:
        """
        判断是否应该重试

        Args:
            error_context: 错误上下文
            attempt: 当前尝试次数

        Returns:
            bool: 是否应该重试
        """
        # 最多重试2次
        if attempt >= 2:
            return False

        error_msg = error_context.error_message

        # 检查是否是不可重试的错误
        for non_retryable in self.non_retryable_errors:
            if non_retryable in error_msg:
                return False

        # 检查是否是可重试的错误
        for retryable in self.retryable_errors:
            if retryable in error_msg:
                return True

        # 根据页面状态决定
        if error_context.page_state == PageState.UNKNOWN:
            # 未知状态可以重试一次
            return attempt == 0

        if error_context.page_state == PageState.DIALOG_OR_POPUP:
            # 弹窗状态可以重试
            return True

        # 默认不重试
        return False

    def get_retry_delay(self, attempt: int) -> float:
        """获取重试延迟（秒）"""
        # 指数退避：1s, 2s
        return 2 ** attempt
```

#### 3.4.2 增强的执行流程

```python
class EnhancedFollowupExecutor(FollowupExecutor):
    """增强版补刀执行器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context_manager = ErrorContextManager(self.adb_service, self._log)
        self.recovery_strategy = RecoveryStrategy(self.adb_service)
        self.validator = RecoveryValidator(self.adb_service)
        self.retry_decision = RetryDecision()

    async def execute(
        self,
        name: str,
        message: str,
        skip_check: bool = False
    ) -> FollowupResult:
        """
        执行补刀（增强版，支持智能恢复和重试）

        Args:
            name: 用户名
            message: 要发送的消息
            skip_check: 是否跳过检查

        Returns:
            FollowupResult: 执行结果
        """
        attempt = 0

        while attempt <= 2:  # 最多3次尝试（初始 + 2次重试）
            try:
                # 0. 确保在主页面
                if not await self.validator.ensure_home_state():
                    return FollowupResult(
                        user_name=name,
                        message=message,
                        status=FollowupStatus.FAILED,
                        error="无法确保主页面状态"
                    )

                # 执行补刀流程
                return await self._execute_followup(name, message, skip_check)

            except Exception as e:
                # 捕获错误上下文
                error_context = await self.context_manager.capture_context(
                    step=f"attempt_{attempt + 1}",
                    error=e,
                    target_user=name,
                    message=message,
                    phase="followup_execution"
                )

                # 判断是否重试
                if not self.retry_decision.should_retry(error_context, attempt):
                    self._log(f"不可重试的错误，放弃: {e}", "ERROR")
                    # 尝试恢复到主页面
                    await self.recovery_strategy.recover_to_home()
                    return FollowupResult(
                        user_name=name,
                        message=message,
                        status=FollowupStatus.FAILED,
                        error=str(e)
                    )

                # 记录重试决策
                self._log(f"准备重试 ({attempt + 1}/2): {e}", "WARN")

                # 尝试恢复到主页面
                recovered = await self.recovery_strategy.recover_to_home()

                if not recovered:
                    self._log("恢复失败，停止重试", "ERROR")
                    return FollowupResult(
                        user_name=name,
                        message=message,
                        status=FollowupStatus.FAILED,
                        error=f"恢复失败: {str(e)}"
                    )

                # 延迟后重试
                delay = self.retry_decision.get_retry_delay(attempt)
                self._log(f"等待 {delay}s 后重试", "INFO")
                await asyncio.sleep(delay)

                attempt += 1

        # 所有尝试都失败
        return FollowupResult(
            user_name=name,
            message=message,
            status=FollowupStatus.FAILED,
            error=f"重试 {attempt} 次后仍失败"
        )
```

### 3.5 数据库持久化

#### 3.5.1 错误日志表

```sql
CREATE TABLE IF NOT EXISTS followup_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    device_serial TEXT NOT NULL,
    target_user TEXT,
    message_to_send TEXT,
    current_step TEXT,
    page_state TEXT,
    ui_tree_hash TEXT,
    error_message TEXT NOT NULL,
    error_traceback TEXT,
    execution_phase TEXT,
    attempt_count INTEGER DEFAULT 0,
    recovered BOOLEAN DEFAULT FALSE,
    INDEX idx_device (device_serial),
    INDEX idx_timestamp (timestamp),
    INDEX idx_user (target_user)
);
```

#### 3.5.2 持久化管理器

```python
class ErrorRepository:
    """错误记录仓库"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def save_error_context(
        self,
        context: ErrorContext,
        device_serial: str,
        attempt: int,
        recovered: bool
    ) -> int:
        """保存错误上下文到数据库"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO followup_errors (
                    device_serial, target_user, message_to_send,
                    current_step, page_state, ui_tree_hash,
                    error_message, error_traceback, execution_phase,
                    attempt_count, recovered
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_serial,
                    context.target_user,
                    context.message_to_send,
                    context.current_step,
                    context.page_state.value,
                    context.ui_tree_hash,
                    context.error_message,
                    context.error_traceback,
                    context.execution_phase,
                    attempt,
                    recovered
                )
            )
            await db.commit()
            return cursor.lastrowid

    async def get_recent_errors(
        self,
        device_serial: str,
        limit: int = 50
    ) -> list[dict]:
        """获取最近的错误记录"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM followup_errors
                WHERE device_serial = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (device_serial, limit)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_error_statistics(
        self,
        device_serial: str,
        days: int = 7
    ) -> dict:
        """获取错误统计信息"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT
                    page_state,
                    COUNT(*) as count,
                    SUM(CASE WHEN recovered = 1 THEN 1 ELSE 0 END) as recovered_count
                FROM followup_errors
                WHERE device_serial = ?
                    AND timestamp > datetime('now', '-' || ? || ' days')
                GROUP BY page_state
                ORDER BY count DESC
                """,
                (device_serial, days)
            )
            rows = await cursor.fetchall()
            return {
                "by_state": [
                    {"state": row[0], "total": row[1], "recovered": row[2]}
                    for row in rows
                ]
            }
```

### 3.6 监控和诊断

#### 3.6.1 实时监控API

```python
from fastapi import APIRouter, HTTPException
from typing import List

router = APIRouter(prefix="/followup/monitoring", tags=["followup-monitoring"])

@router.get("/errors/{device_serial}")
async def get_recent_errors(
    device_serial: str,
    limit: int = 50
) -> List[dict]:
    """获取最近的补刀错误记录"""
    repo = ErrorRepository(get_settings_db_path())
    errors = await repo.get_recent_errors(device_serial, limit)
    return errors

@router.get("/statistics/{device_serial}")
async def get_error_statistics(
    device_serial: str,
    days: int = 7
) -> dict:
    """获取错误统计"""
    repo = ErrorRepository(get_settings_db_path())
    stats = await repo.get_error_statistics(device_serial, days)
    return stats

@router.get("/recovery-rate/{device_serial}")
async def get_recovery_rate(
    device_serial: str,
    days: int = 7
) -> dict:
    """获取恢复成功率"""
    repo = ErrorRepository(get_settings_db_path())
    async with aiosqlite.connect(repo.db_path) as db:
        cursor = await db.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN recovered = 1 THEN 1 ELSE 0 END) as recovered
            FROM followup_errors
            WHERE device_serial = ?
                AND timestamp > datetime('now', '-' || ? || ' days')
            """,
            (device_serial, days)
        )
        row = await cursor.fetchone()
        total, recovered = row
        return {
            "total": total,
            "recovered": recovered,
            "rate": round(recovered / total * 100, 2) if total > 0 else 0
        }
```

#### 3.6.2 前端监控面板

```vue
<template>
  <div class="followup-monitoring">
    <h2>补刀错误监控</h2>

    <!-- 恢复成功率卡片 -->
    <el-card class="stat-card">
      <h3>恢复成功率 (7天)</h3>
      <el-progress :percentage="recoveryRate" :color="getProgressColor(recoveryRate)" />
      <p>{{ recoveredCount }} / {{ totalCount }} 次成功恢复</p>
    </el-card>

    <!-- 错误分布图表 -->
    <el-card class="chart-card">
      <h3>错误状态分布</h3>
      <pie-chart :data="errorDistribution" />
    </el-card>

    <!-- 最近错误列表 -->
    <el-card class="errors-card">
      <h3>最近错误</h3>
      <el-table :data="recentErrors" stripe>
        <el-table-column prop="timestamp" label="时间" width="180" />
        <el-table-column prop="target_user" label="用户" width="120" />
        <el-table-column prop="page_state" label="状态" width="120" />
        <el-table-column prop="error_message" label="错误" />
        <el-table-column label="恢复" width="80">
          <template #default="scope">
            <el-tag :type="scope.row.recovered ? 'success' : 'danger'">
              {{ scope.row.recovered ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="scope">
            <el-button size="small" @click="showErrorDetail(scope.row)"> 详情 </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 错误详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="错误详情" width="60%">
      <div v-if="selectedError">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="时间">
            {{ selectedError.timestamp }}
          </el-descriptions-item>
          <el-descriptions-item label="设备序列号">
            {{ selectedError.device_serial }}
          </el-descriptions-item>
          <el-descriptions-item label="目标用户">
            {{ selectedError.target_user }}
          </el-descriptions-item>
          <el-descriptions-item label="页面状态">
            <el-tag>{{ selectedError.page_state }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="执行步骤">
            {{ selectedError.current_step }}
          </el-descriptions-item>
          <el-descriptions-item label="UI树哈希">
            {{ selectedError.ui_tree_hash }}
          </el-descriptions-item>
          <el-descriptions-item label="错误消息" :span="2">
            {{ selectedError.error_message }}
          </el-descriptions-item>
          <el-descriptions-item label="堆栈信息" :span="2">
            <pre>{{ selectedError.error_traceback }}</pre>
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const deviceSerial = route.params.serial

const recoveryRate = ref(0)
const recoveredCount = ref(0)
const totalCount = ref(0)
const errorDistribution = ref([])
const recentErrors = ref([])
const detailDialogVisible = ref(false)
const selectedError = ref(null)

onMounted(async () => {
  await loadStatistics()
  await loadRecentErrors()
})

async function loadStatistics() {
  const response = await fetch(`/api/followup/monitoring/statistics/${deviceSerial}?days=7`)
  const stats = await response.json()

  const rateResponse = await fetch(`/api/followup/monitoring/recovery-rate/${deviceSerial}?days=7`)
  const rate = await rateResponse.json()

  recoveryRate.value = rate.rate
  recoveredCount.value = rate.recovered
  totalCount.value = rate.total
  errorDistribution.value = stats.by_state
}

async function loadRecentErrors() {
  const response = await fetch(`/api/followup/monitoring/errors/${deviceSerial}?limit=50`)
  recentErrors.value = await response.json()
}

function showErrorDetail(error) {
  selectedError.value = error
  detailDialogVisible.value = true
}

function getProgressColor(rate) {
  if (rate >= 90) return '#67c23a'
  if (rate >= 70) return '#e6a23c'
  return '#f56c6c'
}
</script>
```

## 4. 实施计划

### 4.1 阶段划分

#### 第一阶段：基础增强（1-2周）

**目标**：实现基本的状态识别和恢复机制

**任务**：

1. 实现 `PageStateDetector` 基础版本
   - 识别：主页面、聊天页、搜索页、键盘弹起
   - UI树特征提取和匹配
2. 实现 `RecoveryStrategy` 基础版本
   - 固定策略映射表
   - 基于状态的基础恢复逻辑
3. 增强 `FollowupExecutor` 错误处理
   - 集成状态检测
   - 添加恢复验证

**验收标准**：

- 能识别4种基本页面状态，准确率 > 80%
- 从这4种状态恢复到主页面的成功率 > 90%

#### 第二阶段：完善和优化（1-2周）

**目标**：处理边缘情况，提高可靠性

**任务**：

1. 扩展状态识别
   - 添加：弹窗、系统桌面、搜索结果页
   - 提高识别准确率到 > 90%
2. 优化恢复策略
   - 针对每种状态的最优恢复路径
   - 添加恢复验证机制
3. 实现上下文记录
   - 错误快照功能
   - 日志增强

**验收标准**：

- 能识别7种页面状态，准确率 > 90%
- 所有状态恢复成功率 > 95%

#### 第三阶段：智能重试和监控（1周）

**目标**：实现智能重试和可视化监控

**任务**：

1. 实现智能重试机制
   - 可重试错误判断
   - 指数退避策略
2. 数据库持久化
   - 错误日志表
   - 统计查询
3. 监控面板
   - 后端API
   - 前端UI

**验收标准**：

- 可重试错误自动重试成功率 > 70%
- 监控面板显示实时数据

#### 第四阶段：测试和优化（1周）

**目标**：全面测试，性能优化

**任务**：

1. 单元测试
   - 状态检测器测试
   - 恢复策略测试
   - 各种异常场景模拟
2. 集成测试
   - 真机测试
   - 多设备并发测试
3. 性能优化
   - 状态检测延迟 < 500ms
   - 内存占用优化

**验收标准**：

- 单元测试覆盖率 > 80%
- 集成测试通过率 100%
- 性能指标达标

### 4.2 时间表

```
Week 1-2:  第一阶段 - 基础增强
Week 3-4:  第二阶段 - 完善和优化
Week 5:    第三阶段 - 智能重试和监控
Week 6:    第四阶段 - 测试和优化
```

**总计**：约6周（1.5个月）

### 4.3 风险和缓解

| 风险           | 影响 | 概率 | 缓解措施                       |
| -------------- | ---- | ---- | ------------------------------ |
| UI树特征不稳定 | 高   | 中   | 多特征组合识别，定期更新特征库 |
| 微信版本更新   | 高   | 中   | 抽象化特征提取，版本兼容层     |
| 设备差异       | 中   | 高   | 多设备测试，自适应屏幕尺寸     |
| 性能问题       | 中   | 低   | UI树缓存，异步处理             |
| 开发时间延长   | 低   | 中   | 分阶段交付，核心功能优先       |

## 5. 测试策略

### 5.1 单元测试

```python
# tests/unit/test_page_state_detector.py

import pytest
from wecom_automation.services.followup.recovery import PageStateDetector

@pytest.mark.asyncio
async def test_detect_home_page():
    """测试识别主页面"""
    detector = PageStateDetector(mock_adb_service)

    # Mock UI树返回主页面特征
    mock_adb_service.get_ui_tree.return_value = HOME_UI_TREE

    state = await detector.detect_current_state()
    assert state == PageState.HOME

@pytest.mark.asyncio
async def test_detect_chat_page():
    """测试识别聊天页面"""
    detector = PageStateDetector(mock_adb_service)

    mock_adb_service.get_ui_tree.return_value = CHAT_UI_TREE

    state = await detector.detect_current_state()
    assert state == PageState.CHAT_PAGE

@pytest.mark.asyncio
async def test_detect_keyboard_up():
    """测试识别键盘弹起"""
    detector = PageStateDetector(mock_adb_service)

    mock_adb_service.get_ui_tree.return_value = KEYBOARD_UP_UI_TREE

    state = await detector.detect_current_state()
    assert state == PageState.KEYBOARD_UP

@pytest.mark.asyncio
async def test_ui_tree_cache():
    """测试UI树缓存"""
    detector = PageStateDetector(mock_adb_service)

    # 第一次调用会刷新
    await detector.detect_current_state(refresh=True)
    assert mock_adb_service.get_ui_tree.call_count == 1

    # 第二次调用不刷新，使用缓存
    await detector.detect_current_state(refresh=False)
    assert mock_adb_service.get_ui_tree.call_count == 1
```

### 5.2 集成测试

```python
# tests/integration/test_followup_recovery.py

import pytest
from wecom_automation.services.followup.enhanced_executor import EnhancedFollowupExecutor

@pytest.mark.integration
@pytest.mark.asyncio
async def test_recover_from_chat_page():
    """测试从聊天页面恢复"""
    executor = EnhancedFollowupExecutor(config, device_serial)

    # 1. 进入聊天页面
    await executor._step1_click_search()
    await executor._step2_input_text("test_user")
    await executor._step3_click_result()

    # 2. 验证在聊天页面
    state = await executor.recovery_strategy.detector.detect_current_state()
    assert state == PageState.CHAT_PAGE

    # 3. 恢复
    recovered = await executor.recovery_strategy.recover_to_home()
    assert recovered

    # 4. 验证恢复成功
    is_home, _ = await executor.validator.validate_home_state()
    assert is_home

@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_on_transient_error():
    """测试暂态错误重试"""
    executor = EnhancedFollowupExecutor(config, device_serial)

    # Mock暂态错误（元素未找到）
    with mock.patch.object(
        executor,
        '_step1_click_search',
        side_effect=[Exception("元素未找到"), None]  # 第一次失败，第二次成功
    ):
        result = await executor.execute("test_user", "hello")

    assert result.status == FollowupStatus.SUCCESS
```

### 5.3 压力测试

```python
# tests/stress/test_followup_concurrent.py

import pytest
import asyncio

@pytest.mark.stress
@pytest.mark.asyncio
async def test_concurrent_followup_with_recovery():
    """测试并发补刀的错误恢复"""
    executors = [
        EnhancedFollowupExecutor(config, serial1),
        EnhancedFollowupExecutor(config, serial2),
        EnhancedFollowupExecutor(config, serial3),
    ]

    # 故意制造50%失败率
    users = ["user1", "user2", "user3", "user4", "user5", "user6"]

    tasks = [
        executor.execute(user, "test_message")
        for executor, user in zip(executors, users)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 统计恢复成功率
    recovered = sum(
        1 for r in results
        if not isinstance(r, Exception) and r.status == FollowupStatus.SUCCESS
    )

    recovery_rate = recovered / len(results) * 100
    print(f"恢复成功率: {recovery_rate}%")

    # 目标：即使有50%初始失败率，最终成功率也应该 > 80%
    assert recovery_rate > 80
```

## 6. 文档和培训

### 6.1 技术文档

- **架构文档**：状态检测和恢复机制设计
- **API文档**：新增的监控API接口
- **数据库文档**：错误日志表结构
- **配置文档**：新增的配置项说明

### 6.2 用户文档

- **故障排查指南**：常见错误和解决方案
- **监控面板使用手册**：如何查看错误统计
- **性能调优指南**：如何提高恢复成功率

### 6.3 开发者培训

- **代码审查**：重点审查状态检测逻辑
- **最佳实践**：错误处理模式
- **调试技巧**：如何分析UI树特征

## 7. 成功指标

### 7.1 定量指标

- **恢复成功率**：> 95%
- **状态识别准确率**：> 90%
- **自动重试成功率**：> 70%
- **状态检测延迟**：< 500ms
- **补刀总体成功率提升**：从当前提升 > 20%

### 7.2 定性指标

- **用户体验**：减少手动介入频率
- **可维护性**：清晰的错误日志和上下文
- **可调试性**：完整的监控面板
- **稳定性**：减少卡死和异常退出

## 8. 后续优化方向

### 8.1 机器学习增强

- 使用历史数据训练UI树识别模型
- 自动学习新的页面特征
- 预测最佳恢复路径

### 8.2 自适应策略

- 根据设备性能动态调整检测频率
- 根据历史恢复成功率优化策略
- A/B测试不同恢复策略

### 8.3 跨设备协同

- 多设备状态同步
- 分布式错误分析
- 集群级恢复策略

---

## 附录

### A. 相关文件清单

- `src/wecom_automation/services/followup/recovery.py` - 核心恢复逻辑
- `src/wecom_automation/services/followup/enhanced_executor.py` - 增强执行器
- `src/wecom_automation/services/followup/state_detector.py` - 状态检测器
- `wecom-desktop/backend/routers/followup_monitoring.py` - 监控API
- `wecom-desktop/frontend/src/views/FollowupMonitoring.vue` - 监控面板

### B. 依赖关系

- 需要现有的 `ADBService`、`UIParserService`
- 需要现有的数据库基础设施
- 前端需要 Vue 3 + Element Plus

### C. 兼容性

- Python >= 3.11
- 企业微信版本 >= 4.x
- Android >= 8.0

---

**文档版本**：1.0
**创建日期**：2026-02-06
**作者**：Claude Code
**状态**：待审核
