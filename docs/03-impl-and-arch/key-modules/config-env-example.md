# 环境变量配置说明

WeCom Automation 支持通过环境变量配置数据库路径和其他设置。

## 数据库路径配置

### 方式1：环境变量（推荐）

```bash
# Windows PowerShell
$env:WECOM_DB_PATH = "D:\111\android_run_test-main\wecom_conversations.db"

# Windows CMD
set WECOM_DB_PATH=D:\111\android_run_test-main\wecom_conversations.db

# Linux/Mac
export WECOM_DB_PATH=/path/to/wecom_conversations.db
```

### 方式2：项目根目录环境变量

```bash
$env:WECOM_PROJECT_ROOT = "D:\111\android_run_test-main"
# 数据库将自动使用: D:\111\android_run_test-main\wecom_conversations.db
```

### 默认行为

如果未设置环境变量，数据库路径按以下优先级确定：

1. `WECOM_DB_PATH` 环境变量
2. 项目根目录 / `wecom_conversations.db`

**项目根目录** = `android_run_test-main/`（通过代码位置自动计算）

## 完整环境变量列表

| 变量名                    | 默认值                                  | 说明                 |
| ------------------------- | --------------------------------------- | -------------------- |
| `WECOM_DB_PATH`           | `{PROJECT_ROOT}/wecom_conversations.db` | 数据库文件路径       |
| `WECOM_PROJECT_ROOT`      | 自动计算                                | 项目根目录           |
| `WECOM_DEVICE_SERIAL`     | -                                       | 指定设备序列号       |
| `WECOM_USE_TCP`           | `false`                                 | TCP 模式连接设备     |
| `WECOM_TIMEZONE`          | `Asia/Shanghai`                         | 时区配置             |
| `WECOM_WAIT_AFTER_LAUNCH` | `3.0`                                   | 启动后等待时间（秒） |
| `WECOM_SCROLL_DELAY`      | `1.0`                                   | 滚动延迟（秒）       |
| `WECOM_MAX_SCROLLS`       | `20`                                    | 最大滚动次数         |
| `WECOM_STABLE_THRESHOLD`  | `4`                                     | 稳定阈值             |
| `WECOM_OUTPUT_DIR`        | `.`                                     | 输出目录             |
| `WECOM_LOG_FILE`          | -                                       | 日志文件路径         |
| `WECOM_CAPTURE_AVATARS`   | `false`                                 | 是否保存头像         |
| `WECOM_DEBUG`             | `false`                                 | 调试模式             |

## 代码中使用

```python
from wecom_automation.core.config import (
    get_default_db_path,  # 获取数据库路径
    get_project_root,     # 获取项目根目录
    PROJECT_ROOT,         # 项目根目录常量
    DEFAULT_DB_PATH,      # 数据库路径常量
)

# 获取数据库路径
db_path = get_default_db_path()
print(f"Database: {db_path}")
# 输出: D:\111\android_run_test-main\wecom_conversations.db

# 在配置类中使用
from wecom_automation.core.config import Config
config = Config.from_env()
print(config.db_path)
```

## 注意事项

1. **路径统一**：所有模块现在使用统一的 `get_default_db_path()` 函数
2. **向后兼容**：旧代码中的 `PROJECT_ROOT` 和 `get_db_path()` 仍然可用
3. **无需重启**：环境变量在程序启动时读取，运行时不会自动更新
