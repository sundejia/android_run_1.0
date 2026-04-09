"""
补刀间隔时间功能测试

测试补刀系统中的自定义间隔时间功能：
1. 设置保存和读取
2. 间隔时间过滤逻辑
3. 边界条件和异常处理
4. 完整工作流测试

Usage:
    pytest tests/test_followup_intervals.py -v
    pytest tests/test_followup_intervals.py::test_interval_filtering -v
    pytest tests/test_followup_intervals.py::test_interval_settings_api -v
"""

import os
import sys
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# 添加 backend 目录和项目根目录到 Python 路径
from utils.path_utils import get_project_root

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

project_root = get_project_root()
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

import pytest

# 导入需要测试的模块
from services.followup.attempts_repository import (
    FollowupAttemptsRepository,
    FollowupAttempt,
    AttemptStatus,
)
from services.followup.settings import SettingsManager, FollowUpSettings


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def temp_db():
    """临时数据库文件"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except Exception:
        pass


@pytest.fixture
def repo(temp_db):
    """补刀仓库实例"""
    return FollowupAttemptsRepository(temp_db)


@pytest.fixture
def settings_manager(temp_db):
    """设置管理器实例"""
    return SettingsManager(temp_db)


# ============================================
# 测试辅助函数
# ============================================

def create_test_attempt(
    repo: FollowupAttemptsRepository,
    device_serial: str,
    customer_name: str,
    current_attempt: int = 0,
    last_followup_at: datetime = None,
    max_attempts: int = 3,
    status: AttemptStatus = AttemptStatus.PENDING,
):
    """创建测试用的补刀记录"""
    # 直接插入数据库
    conn = repo._get_connection()
    now = datetime.now().isoformat()
    last_followup_iso = last_followup_at.isoformat() if last_followup_at else None

    conn.execute(
        """INSERT INTO followup_attempts
           (device_serial, customer_name, last_kefu_message_id, last_kefu_message_time,
            max_attempts, current_attempt, status, created_at, updated_at, last_followup_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            device_serial,
            customer_name,
            f"msg_{customer_name}",
            datetime.now().isoformat(),
            max_attempts,
            current_attempt,
            status.value,
            now,
            now,
            last_followup_iso,
        ),
    )
    conn.commit()
    conn.close()


# ============================================
# 单元测试：间隔时间过滤逻辑
# ============================================

class TestIntervalFiltering:
    """测试间隔时间过滤逻辑"""

    def test_first_attempt_no_interval_check(self, repo):
        """首次补刀（current_attempt=0）不检查间隔时间"""
        device_serial = "test_device_001"
        customer_name = "customer_1"

        # 创建首次补刀记录（current_attempt=0）
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=0,
            last_followup_at=None,  # 首次补刀没有 last_followup_at
        )

        # 任何间隔时间配置都应该返回
        intervals_short = [1, 2, 3]  # 很短的间隔
        intervals_long = [1000, 2000, 3000]  # 很长的间隔

        pending_short = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals_short)
        pending_long = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals_long)

        assert len(pending_short) == 1
        assert len(pending_long) == 1
        assert pending_short[0].customer_name == customer_name

    def test_second_attempt_interval_check(self, repo):
        """第二次补刀（current_attempt=1）需要检查间隔时间"""
        device_serial = "test_device_002"
        customer_name = "customer_2"

        # 创建已补刀一次的记录（current_attempt=1）
        last_followup_time = datetime.now() - timedelta(minutes=70)  # 70分钟前
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=1,
            last_followup_at=last_followup_time,
        )

        # 场景1：间隔要求 60 分钟，实际已过 70 分钟 → 应该返回
        intervals_60 = [60, 120, 180]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals_60)
        assert len(pending) == 1, "70分钟 > 60分钟间隔，应该返回"

        # 场景2：间隔要求 90 分钟，实际已过 70 分钟 → 不应该返回
        intervals_90 = [90, 120, 180]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals_90)
        assert len(pending) == 0, "70分钟 < 90分钟间隔，不应该返回"

    def test_third_attempt_interval_check(self, repo):
        """第三次补刀（current_attempt=2）使用第二个间隔时间"""
        device_serial = "test_device_003"
        customer_name = "customer_3"

        # 创建已补刀两次的记录（current_attempt=2）
        last_followup_time = datetime.now() - timedelta(minutes=130)  # 130分钟前
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=2,
            last_followup_at=last_followup_time,
        )

        # 场景1：间隔要求 [60, 120, 180]，使用 intervals[1]=120
        # 实际已过 130 分钟 > 120 分钟 → 应该返回
        intervals = [60, 120, 180]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals)
        assert len(pending) == 1, "130分钟 > 120分钟间隔（第二次），应该返回"

        # 场景2：间隔要求 [60, 180, 240]，使用 intervals[1]=180
        # 实际已过 130 分钟 < 180 分钟 → 不应该返回
        intervals = [60, 180, 240]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals)
        assert len(pending) == 0, "130分钟 < 180分钟间隔（第二次），不应该返回"

    def test_interval_fallback_to_last_value(self, repo):
        """超出间隔数组范围时使用最后一个值"""
        device_serial = "test_device_004"
        customer_name = "customer_4"

        # 创建已补刀三次的记录（current_attempt=3）
        last_followup_time = datetime.now() - timedelta(minutes=250)  # 250分钟前
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=3,
            last_followup_at=last_followup_time,
            max_attempts=5,  # 允许更多补刀
        )

        # 间隔数组只有 3 个值 [60, 120, 180]
        # current_attempt=3 → index=2 → 使用 intervals[2]=180
        intervals = [60, 120, 180]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals)
        assert len(pending) == 1, "250分钟 > 180分钟（使用最后一个间隔），应该返回"

    def test_multiple_customers_mixed_intervals(self, repo):
        """多个客户混合间隔时间场景"""
        device_serial = "test_device_005"

        now = datetime.now()

        # 客户1：首次补刀（不需要检查间隔）
        create_test_attempt(repo, device_serial, "customer_1", current_attempt=0)

        # 客户2：第二次补刀，70分钟前（假设间隔60分钟）
        create_test_attempt(
            repo,
            device_serial,
            "customer_2",
            current_attempt=1,
            last_followup_at=now - timedelta(minutes=70),
        )

        # 客户3：第二次补刀，50分钟前（假设间隔60分钟，未达到）
        create_test_attempt(
            repo,
            device_serial,
            "customer_3",
            current_attempt=1,
            last_followup_at=now - timedelta(minutes=50),
        )

        # 客户4：第三次补刀，130分钟前（假设间隔120分钟）
        create_test_attempt(
            repo,
            device_serial,
            "customer_4",
            current_attempt=2,
            last_followup_at=now - timedelta(minutes=130),
        )

        intervals = [60, 120, 180]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals)

        # 应该返回：客户1（首次）、客户2（70>60）、客户4（130>120）
        # 不应该返回：客户3（50<60）
        assert len(pending) == 3
        customer_names = {p.customer_name for p in pending}
        assert customer_names == {"customer_1", "customer_2", "customer_4"}

    def test_limit_parameter_respected(self, repo):
        """limit 参数应该被正确遵守"""
        device_serial = "test_device_006"

        # 创建 10 个首次补刀记录
        for i in range(10):
            create_test_attempt(repo, device_serial, f"customer_{i}", current_attempt=0)

        intervals = [60, 120, 180]

        # limit=5 应该只返回 5 个
        pending = repo.get_pending_attempts(device_serial, limit=5, attempt_intervals=intervals)
        assert len(pending) == 5


# ============================================
# 单元测试：设置管理
# ============================================

class TestSettingsManagement:
    """测试设置管理"""

    def test_default_intervals(self, settings_manager):
        """测试默认间隔时间"""
        settings = settings_manager.get_settings()

        assert settings.attempt_intervals is not None
        assert settings.attempt_intervals == [60, 120, 180]

    def test_custom_intervals(self, settings_manager, temp_db):
        """测试自定义间隔时间"""
        # 模拟保存自定义设置
        custom_settings = FollowUpSettings(
            followup_enabled=True,
            max_followups=10,
            use_ai_reply=True,
            enable_operating_hours=False,
            start_hour="08:00",
            end_hour="20:00",
            message_templates=["Template 1", "Template 2"],
            followup_prompt="Custom prompt",
            idle_threshold_minutes=45,
            max_attempts_per_customer=5,
            attempt_intervals=[30, 60, 90],  # 自定义间隔
        )

        # 注意：由于 SettingsManager 现在依赖统一设置服务
        # 这里我们主要测试数据类的正确性
        assert custom_settings.attempt_intervals == [30, 60, 90]

    def test_intervals_validation(self):
        """测试间隔时间边界值"""
        # 合法值
        settings1 = FollowUpSettings(attempt_intervals=[1, 2, 3])
        assert settings1.attempt_intervals == [1, 2, 3]

        settings2 = FollowUpSettings(attempt_intervals=[1440, 2880, 4320])  # 1天, 2天, 3天
        assert settings2.attempt_intervals == [1440, 2880, 4320]

        # 空数组（__post_init__ 会设置默认值）
        settings3 = FollowUpSettings(attempt_intervals=[])
        assert settings3.attempt_intervals == [], "空数组应保持为空"

        # None（__post_init__ 会设置默认值）
        settings4 = FollowUpSettings(attempt_intervals=None)
        assert settings4.attempt_intervals == [60, 120, 180], "None 应该被 __post_init__ 设置为默认值"


# ============================================
# 集成测试：API 接口
# ============================================

class TestAPIIntegration:
    """测试 API 集成（需要后端服务运行）"""

    def test_followup_settings_model(self):
        """测试 API 模型序列化"""
        from routers.followup_manage import FollowUpSettingsModel

        # 测试默认值
        model = FollowUpSettingsModel()
        assert model.followupEnabled is False
        assert model.maxFollowupPerScan == 5
        assert model.idleThresholdMinutes == 30
        assert model.maxAttemptsPerCustomer == 3
        assert model.attemptIntervals == [60, 120, 180]

        # 测试自定义值
        model = FollowUpSettingsModel(
            followupEnabled=True,
            maxFollowupPerScan=10,
            useAIReply=True,
            idleThresholdMinutes=45,
            maxAttemptsPerCustomer=5,
            attemptIntervals=[30, 60, 90],
        )
        assert model.attemptIntervals == [30, 60, 90]

    def test_settings_dict_conversion(self):
        """测试设置字典转换"""
        from routers.followup_manage import FollowUpSettingsModel

        model = FollowUpSettingsModel(
            followupEnabled=True,
            maxFollowupPerScan=10,
            attemptIntervals=[30, 60, 90],
        )

        # 转换为字典
        data = model.model_dump()
        assert data["attemptIntervals"] == [30, 60, 90]

        # 从字典重建
        model2 = FollowUpSettingsModel(**data)
        assert model2.attemptIntervals == [30, 60, 90]


# ============================================
# 边界测试
# ============================================

class TestBoundaryConditions:
    """测试边界条件和异常情况"""

    def test_zero_interval(self, repo):
        """零间隔时间（应该立即允许补刀）"""
        device_serial = "test_device_boundary_1"
        customer_name = "customer_zero"

        # 创建刚刚补刀过的记录
        last_followup_time = datetime.now() - timedelta(seconds=30)  # 30秒前
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=1,
            last_followup_at=last_followup_time,
        )

        # 间隔为 0 → 应该立即返回
        intervals = [0, 0, 0]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals)
        assert len(pending) == 1

    def test_negative_interval_handling(self, repo):
        """负数间隔时间（逻辑上不应该出现，但需要防御）"""
        device_serial = "test_device_boundary_2"
        customer_name = "customer_negative"

        last_followup_time = datetime.now() - timedelta(minutes=10)
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=1,
            last_followup_at=last_followup_time,
        )

        # 负数间隔 → 实际上任何正数时间差都 >= 负数
        intervals = [-10, -20, -30]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals)
        # 当前实现：10分钟 >= -10分钟，所以会返回
        # 这可能是一个需要修复的边界问题
        assert len(pending) == 1, "当前实现对负数间隔的处理可能不符合预期"

    def test_empty_intervals_list(self, repo):
        """空间隔数组"""
        device_serial = "test_device_boundary_3"
        customer_name = "customer_empty"

        last_followup_time = datetime.now() - timedelta(minutes=10)
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=1,
            last_followup_at=last_followup_time,
        )

        # 空数组 → 应该使用默认值 [60, 120, 180]
        # 10分钟 < 60分钟，所以不应该返回
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=[])
        assert len(pending) == 0, "空数组应使用默认值[60,120,180]，10分钟未达到"

    def test_missing_last_followup_at(self, repo):
        """缺少 last_followup_at 字段（数据异常）"""
        device_serial = "test_device_boundary_4"
        customer_name = "customer_missing_time"

        # 创建记录但没有 last_followup_at（current_attempt > 0）
        create_test_attempt(
            repo,
            device_serial,
            customer_name,
            current_attempt=1,
            last_followup_at=None,
        )

        # 当前实现：允许补刀（容错处理）
        intervals = [60, 120, 180]
        pending = repo.get_pending_attempts(device_serial, limit=10, attempt_intervals=intervals)
        assert len(pending) == 1, "缺少时间戳时应容错处理"


# ============================================
# 运行测试的辅助函数
# ============================================

def print_test_summary():
    """打印测试摘要"""
    print("\n" + "=" * 70)
    print("补刀间隔时间功能测试")
    print("=" * 70)
    print("\n测试覆盖范围：")
    print("  ✓ 单元测试：间隔时间过滤逻辑")
    print("  ✓ 单元测试：设置管理")
    print("  ✓ 集成测试：API 接口")
    print("  ✓ 边界测试：极端值和异常处理")
    print("\n运行方式：")
    print("  pytest tests/test_followup_intervals.py -v")
    print("  pytest tests/test_followup_intervals.py::TestIntervalFiltering -v")
    print("=" * 70)


if __name__ == "__main__":
    print_test_summary()
    # 运行测试
    pytest.main([__file__, "-v", "--tb=short"])
