# Test Organization Rules

## Overview

本项目所有测试文件必须放在指定的测试目录中，不允许散落在项目各处。

## Test Directory Structure

```
project-root/
├── tests/                              # ← Python 主测试目录
│   ├── __init__.py
│   ├── conftest.py                     # pytest 配置和 fixtures
│   ├── unit/                           # 单元测试
│   │   ├── __init__.py
│   │   ├── test_*.py                   # 单元测试文件
│   │   └── ...
│   └── integration/                    # 集成测试
│       ├── __init__.py
│       ├── test_*.py                   # 集成测试文件
│       └── ...
│
└── wecom-desktop/
    └── backend/
        └── tests/                      # ← 后端 API 测试目录
            ├── __init__.py
            ├── test_*.py               # 后端 API 测试
            └── ...
```

## Rules

### 1. 所有测试文件必须放在 `tests/` 目录

**禁止**：在项目根目录或其他位置创建 `test_*.py` 文件

```bash
# ❌ 错误位置
project-root/test_something.py
project-root/debug_test.py
src/test_utils.py

# ✅ 正确位置
tests/unit/test_something.py
tests/integration/test_debug.py
```

### 2. 按测试类型分类

| 测试类型          | 目录                           | 说明                              |
| ----------------- | ------------------------------ | --------------------------------- |
| **单元测试**      | `tests/unit/`                  | 快速、无外部依赖、测试单个函数/类 |
| **集成测试**      | `tests/integration/`           | 需要设备连接或外部服务            |
| **后端 API 测试** | `wecom-desktop/backend/tests/` | 测试 FastAPI 路由和后端服务       |

### 3. 测试文件命名规范

```python
# 格式: test_<module_name>.py
test_ui_parser.py           # 测试 ui_parser 模块
test_timestamp_parser.py    # 测试 timestamp_parser 模块
test_sync_service.py        # 测试 sync_service 模块

# 对于后端 API 测试
test_sidecar_api.py         # 测试 sidecar API
test_followup_device_manager.py  # 测试 followup 设备管理
```

### 4. 禁止的测试文件位置

以下位置**不允许**存放测试文件：

```
❌ 项目根目录: test_*.py, debug_*.py
❌ src/ 下: src/**/test_*.py
❌ scripts/ 下: scripts/test_*.py
❌ docs/ 下: docs/test_*.py
```

### 5. 临时/手动测试脚本

如果需要创建临时测试/调试脚本（不属于自动化测试套件）：

```bash
# 选项 1: 放在 scripts/ 目录（如果是可复用的脚本）
scripts/debug_ui_extraction.py

# 选项 2: 放在 tests/manual/ 目录（手动测试场景）
tests/manual/verify_avatar_capture.py

# 选项 3: 使用 .gitignore 排除
# 在根目录创建，但不提交到 git
debug_*.py  # 添加到 .gitignore
```

## Pytest Configuration

`pyproject.toml` 中的配置确保 pytest 只扫描指定目录：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]  # 只扫描 tests/ 目录
asyncio_mode = "auto"
addopts = "-v --tb=short"
markers = [
    "unit: Unit tests (fast, no external dependencies)",
    "integration: Integration tests (require device connection)",
]
```

## Running Tests

```bash
# 运行所有测试
pytest

# 运行单元测试（快速）
pytest tests/unit

# 运行集成测试
pytest tests/integration

# 运行特定测试文件
pytest tests/unit/test_ui_parser.py

# 桌面 FastAPI 测试（根目录 pytest 的 testpaths 默认仅为 tests/ 时）
pytest wecom-desktop/backend/tests/test_media_actions_api.py --override-ini="testpaths=."

# 运行特定测试函数
pytest tests/unit/test_ui_parser.py::test_extract_messages

# 使用标记
pytest -m unit              # 只运行单元测试
pytest -m integration       # 只运行集成测试
```

## For AI Assistants

当创建新测试时，请遵循以下规则：

1. **确定测试类型**
   - 单元测试（无外部依赖）→ `tests/unit/test_<module>.py`
   - 集成测试（需要设备/服务）→ `tests/integration/test_<feature>.py`
   - 后端 API 测试 → `wecom-desktop/backend/tests/test_<api>.py`

2. **文件命名**
   - 使用 `test_` 前缀
   - 与被测试模块同名
   - 使用小写和下划线

3. **文件位置检查**
   - 在创建测试文件前，检查是否在正确的 `tests/` 目录下
   - 如果用户要求创建测试，默认放在 `tests/unit/`
   - 如果涉及 API 路由测试，放在 `wecom-desktop/backend/tests/`

4. **禁止行为**
   - 不要在项目根目录创建 `test_*.py`
   - 不要在 `src/` 下创建测试文件
   - 不要创建散落的调试脚本（除非明确添加到 `.gitignore`）

## Example Test Structure

### Unit Test Example

```python
# tests/unit/test_timestamp_parser.py

import pytest
from wecom_automation.services.timestamp_parser import TimestampParser

class TestTimestampParser:
    """Test suite for TimestampParser."""

    def test_parse_today_format(self):
        parser = TimestampParser()
        result = parser.parse("14:30")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_parse_yesterday_format(self):
        parser = TimestampParser()
        result = parser.parse("昨天 14:30")
        assert result is not None
```

### Integration Test Example

```python
# tests/integration/test_device_connection.py

import pytest

@pytest.mark.integration
async def test_connect_to_device():
    """Test ADB device connection."""
    # This test requires a physical device
    pass
```

## Migration Guide

如果发现测试文件在错误位置：

1. **移动文件到正确目录**

   ```bash
   git mv test_something.py tests/unit/test_something.py
   ```

2. **更新 import 路径**（如果需要）

   ```python
   # 旧
   from test_utils import helper

   # 新
   from tests.unit.test_utils import helper
   ```

3. **运行测试确认**
   ```bash
   pytest tests/unit/test_something.py
   ```
