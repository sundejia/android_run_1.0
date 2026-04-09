# 企业微信自动化

> **Android 设备企业微信自动化框架**
>
> 基于 DroidRun 非 LLM API 的模块化企业微信自动化框架

**[English](README.md)** | **[📚 文档索引](docs/INDEX.md)**

## 功能特性

### 核心自动化框架

- ✅ **启动企业微信**: 通过 ADB 自动启动企业微信应用
- ✅ **导航到私聊**: 切换消息过滤器到"私聊"
- ✅ **获取当前用户名**: 从 UI 中提取当前登录的企业微信用户名（客服）
- ✅ **提取用户详情**: 提取所有用户的姓名、渠道、日期、消息预览和头像
- ✅ **提取会话消息**: 提取会话中的所有消息（文本、图片、语音、系统消息）
- ✅ **提取未读消息**: 根据头像右上角的红点数字识别有未读消息的用户
- ✅ **自动滚动提取**: 滚动整个列表并去重
- ✅ **头像截图**: 通过智能边界检测捕获头像图片
- ✅ **图片消息下载**: 从会话中下载图片消息到本地文件
- ✅ **表格输出**: 以格式化表格显示结果
- ✅ **模块化架构**: 清晰的关注点分离，易于维护
- ✅ **全面测试**: 320+ 单元测试，支持集成测试
- ✅ **DroidRun 叠加层优化**: 针对 DroidRun 叠加层功能优化，包含缓存、O(1) 查找和平面列表优化

### 桌面应用 (wecom-desktop)

- ✅ **桌面 GUI**: 基于 Electron 的桌面应用，用于管理企业微信自动化
- ✅ **设备镜像**: 通过 scrcpy 集成实现实时屏幕镜像
- ✅ **多设备支持**: 同时连接和管理多个 Android 设备
- ✅ **并行同步**: 在多个设备上并行运行初始同步操作，使用独立进程
- ✅ **实时状态**: 基于 WebSocket 的每设备隔离状态流
- ✅ **实时日志**: 从每个设备的同步进程实时流式传输日志
- ✅ **Sidecar 视图**: 实时镜像感知上下文（客服信息、最近消息），带有 10 秒延迟发送功能，当检测到设备上输入时自动暂停
- ✅ **进程隔离**: 每个设备在自己的子进程中运行，确保稳定性
- ✅ **按设备同步媒体目录**: 多设备同步默认写入 `device_storage/<serial>/conversation_*`，避免多个设备共用一个媒体输出目录
- ✅ **优雅停止**: 随时停止任何设备的同步而不影响其他设备
- ✅ **仪表板**: 统一视图展示同步的会话、设备、客服和客户，以及聚合统计
- ✅ **客服下钻**: 浏览/搜索客服，查看每个代理的详细卡片，并深入他们的客户
- ✅ **客户下钻**: 浏览所有同步的客户，支持搜索、分页和确定性头像分配
- ✅ **客户详情视图**: 查看单个客户的会话，包含消息细分和历史记录
- ✅ **设备详情页**: 全面的设备信息页面，包含硬件规格、系统信息、连接详情和快速操作（同步、镜像、日志）

## 最近更新 (2026-02-05)

- **架构审查**: 完成全面代码审计 ([查看报告](docs/05-changelog-and-upgrades/2026-02-05-architecture-review.md))
- **代码清理**: 移除弃用功能（学习建议、提示词更新）
- **路径统一**: 引入 `get_project_root()` 实现一致的路径解析
- **脚本重组**: 将脚本移动到 `wecom-desktop/backend/scripts/`
- **客服提取**: 将独立脚本整合到后端工具模块

## 系统要求

### 核心框架

- Python >= 3.11
- [uv](https://github.com/astral-sh/uv) 包管理器
- 已启用 USB 调试的 Android 设备
- 设备上安装的企业微信

### 桌面应用（可选）

- Node.js >= 18.x
- 已安装 scrcpy 并在 PATH 中（用于设备镜像）
- 已安装 ADB 并在 PATH 中

## 快速开始

### 安装

```bash
# 克隆并设置
git clone <repo-url>
cd android_run_test-backup

# 创建虚拟环境并安装
uv venv --python 3.11
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

### 开发设置（可选）

设置 Git 钩子以提高代码质量（推荐给贡献者）：

```bash
# 安装根依赖（Husky、commitlint、lint-staged）
npm install

# 安装前端依赖（ESLint、Prettier）
cd wecom-desktop && npm install && cd ..

# Git 钩子现在激活
# - pre-commit: 检查和格式化暂存文件
# - commit-msg: 验证提交消息格式
# - pre-push: 运行类型检查和单元测试
```

详情请参阅 `docs/00-meta/how-we-document.md`。

### 快速命令

```bash
# 列出所有会话并捕获头像
uv run wecom-automation --skip-launch --capture-avatars --output-dir ./output

# 列出已连接的 Android 设备及详情
uv run list_devices.py --full --detailed

# 启动桌面应用（推荐用于多设备管理）
cd wecom-desktop && npm start
```

---

### 列出所有会话并捕获头像

#### 方案 1：CLI 命令（推荐）

列出所有会话并捕获头像的最简单方法：

```bash
# 完整工作流：启动企业微信、切换到私聊、提取用户及头像
wecom-automation --capture-avatars --output-dir ./output

# 如果企业微信已打开，跳过启动步骤
wecom-automation --skip-launch --capture-avatars --output-dir ./output

# 同时导出结果到 JSON
wecom-automation --skip-launch --capture-avatars --output-json users.json --output-dir ./output

# 调试模式，详细日志
wecom-automation --skip-launch --capture-avatars --debug --log-file debug.log
```

头像将保存到 `./output/avatars/`，文件名如 `avatar_01_张三.png`。

#### 方案 2：编程方式

在自己的 Python 代码中使用：

```python
import asyncio
from wecom_automation.core.config import Config
from wecom_automation.services import WeComService

async def main():
    config = Config()
    service = WeComService(config)

    # 运行完整工作流并捕获头像
    result = await service.run_full_workflow(
        skip_launch=False,        # 如果企业微信已打开，设为 True
        capture_avatars=True,     # 启用头像截图
        output_dir="./output"     # 保存头像的位置
    )

    # 打印结果
    print(f"找到 {result.total_count} 个用户")
    print(result.format_table())  # 漂亮的表格输出

    # 访问单个用户
    for user in result.users:
        print(f"姓名: {user.name}")
        print(f"渠道: {user.channel}")
        print(f"日期: {user.last_message_date}")
        print(f"预览: {user.message_preview}")
        if user.avatar and user.avatar.screenshot_path:
            print(f"头像已保存: {user.avatar.screenshot_path}")

asyncio.run(main())
```

#### 方案 3：逐步控制

更细粒度的控制：

```python
import asyncio
from wecom_automation.core.config import Config
from wecom_automation.services import WeComService

async def extract_with_avatars():
    service = WeComService(Config())

    # 步骤 1：启动企业微信
    await service.launch_wecom()

    # 步骤 2：导航到私聊
    await service.switch_to_private_chats()

    # 步骤 3：提取用户并捕获头像
    result = await service.extract_private_chat_users(
        max_scrolls=30,
        capture_avatars=True,
        output_dir="./output"
    )

    return result

asyncio.run(extract_with_avatars())
```

### 头像提取工作原理

头像提取是一个多步骤过程，从企业微信会话列表中捕获个人资料图片：

1. **检测**: 在用户提取期间，系统通过资源 ID 和边界检测 UI 树中的头像元素
2. **边界解析**: 从可访问性树中以 `[x1,y1][x2,y2]` 格式提取头像边界
3. **截图捕获**: 在列表滚动时捕获完整截图
4. **裁剪**: 使用检测到的边界从截图中裁剪头像
5. **验证**: 保存前验证边界（大小、位置、宽高比）
6. **保存**: 有效头像保存为 PNG 文件

#### 头像文件位置

启用 `--capture-avatars` 时，头像保存到：

```
{output_dir}/avatars/avatar_{index:02d}_{name}.png
```

示例：

```
./output/avatars/avatar_01_张三.png
./output/avatars/avatar_02_John_Smith.png
./output/avatars/avatar_03_Li_Si.png
```

---

### 桌面应用 (wecom-desktop)

使用由 Electron 和 Vue.js 构建的图形界面管理多个设备并运行并行同步操作。

#### 快速开始

```bash
# 安装 Node.js 依赖
cd wecom-desktop
npm install

# 安装 Python 后端依赖
cd backend
pip install -r requirements.txt
# 或使用 uv:
uv pip install fastapi uvicorn websockets pydantic

# 启动后端（终端 1）
cd backend
uvicorn main:app --reload --port 8765

# 启动 Electron 应用（终端 2）
cd ..
npm run dev:electron
```

#### 重要：多设备端口配置

在多个设备上同时运行同步时，每个设备的 droidrun 应用必须配置唯一的端口：

- 设备 1：Socket Server Port = 8080
- 设备 2：Socket Server Port = 8081
- 设备 3：Socket Server Port = 8082
- ...

这可以防止导致同步失败的端口冲突。

详情请参阅 [wecom-desktop/README.md](wecom-desktop/README.md)。

---

## 项目结构

```
android_run_test-backup/
├── docs/                           # 📚 文档 (248 个文件)
│   ├── 00-meta/                    # 元文档
│   ├── 01-product/                 # 功能规格
│   ├── 02-prompts-and-iterations/  # AI 提示和会话日志
│   ├── 03-impl-and-arch/          # 实现和架构
│   │   └── old-archive/            # ⚠️ 已归档的完成任务 (26 个文件)
│   ├── 04-bugs-and-fixes/          # Bug 跟踪
│   ├── 05-changelog-and-upgrades/  # 版本历史
│   └── INDEX.md                    # 📖 文档索引
├── src/
│   └── wecom_automation/           # 主包
│       ├── __init__.py             # 包导出和版本 (v0.2.1)
│       ├── core/                   # 🏗️ 基础层
│       │   ├── config.py           # 配置管理
│       │   ├── exceptions.py       # 自定义异常层次
│       │   ├── models.py           # 数据模型 (dataclasses)
│       │   └── logging.py          # 结构化日志工具
│       ├── services/               # ⚙️ 业务逻辑层
│       │   ├── adb_service.py      # 低级 ADB 交互
│       │   ├── device_service.py   # 设备发现和枚举
│       │   ├── ui_parser.py        # UI 树解析
│       │   └── wecom_service.py    # 高级编排
│       └── cli/                    # 🖥️ 用户界面层
│           └── commands.py         # CLI 入口点
├── wecom-desktop/                  # 🖥️ 桌面应用
│   ├── electron/                   # Electron 主进程
│   ├── src/                        # Vue.js 渲染器
│   └── backend/                    # FastAPI 后端
├── tests/                          # 🧪 测试套件
│   ├── unit/                       # 单元测试 (320+ 测试)
│   └── integration/                # 集成测试
├── list_devices.py                 # 🔧 设备发现脚本（调试用）
├── verify_messages_screen.py       # 🔍 验证当前屏幕是否为消息屏幕
├── pyproject.toml                  # 项目配置和依赖
├── uv.lock                         # 锁定的依赖
├── README.md                       # 英文文档
└── README_zh.md                    # 📖 中文文档（本文件）
```

---

## 系统架构

### 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户界面层                                      │
├────────────────────────────────┬────────────────────────────────────────────┤
│     Electron 桌面应用           │           命令行工具                        │
│   (Vue.js + Pinia + scrcpy)    │      (wecom-automation)                     │
└────────────────┬───────────────┴────────────────────┬───────────────────────┘
                 │ REST + WebSocket                   │ 直接调用
                 ▼                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI 后端服务                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │    路由层    │  │    服务层    │  │   工作进程   │  │   WebSocket    │  │
│  │  (21 文件)   │  │  (12 文件)   │  │  (scripts/)  │  │     管理器     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────────┘  │
└────────────────────────────────┬───────────────────────────────────────────┘
                                 │ import / subprocess
                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         核心自动化库                                        │
│                    (wecom_automation 包)                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │     Core     │  │   Services   │  │   Database   │  │   Handlers     │  │
│  │  (模型、配置) │  │ (ADB、UI、   │  │ (SQLite、    │  │  (消息类型     │  │
│  │             │  │   WeCom)     │  │  repository) │  │   处理器)      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────────┘  │
└────────────────────────────────┬───────────────────────────────────────────┘
                                 │ ADB 命令
                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         Android 设备层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │   DroidRun   │  │     ADB      │  │    scrcpy    │  │   企业微信     │  │
│  │   (叠加层)   │  │   (控制)     │  │   (镜像)     │  │   (目标应用)   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

### 三层架构（核心库）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CLI 层 (cli/)                                       │
│   commands.py: 参数解析、配置构建、工作流执行                                  │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ 使用
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        服务层 (services/)                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  WeComService (编排器)                                              │    │
│  │  • launch_wecom() → switch_to_private_chats() → extract_users()     │    │
│  │  • 头像捕获、会话提取、客服检测                                       │    │
│  └───────────────┬────────────────────────────┬────────────────────────┘    │
│                  │                            │                              │
│     ┌────────────▼────────────┐  ┌────────────▼────────────┐                │
│     │      ADBService         │  │    UIParserService      │                │
│     │  • 设备连接              │  │  • UI 树解析            │                │
│     │  • 应用启动/控制         │  │  • 元素检测             │                │
│     │  • 点击/滑动/滚动        │  │  • 用户提取             │                │
│     │  • 截图                  │  │  • 模式匹配             │                │
│     └────────────┬────────────┘  └─────────────────────────┘                │
│                  │                                                           │
│     ┌────────────▼────────────────────────────────────────────────────┐     │
│     │  专业服务                                                        │     │
│     │  • SyncOrchestrator: 数据库同步（带断点续传）                     │     │
│     │  • MessageHandlers: 文本、图片、语音、视频处理                    │     │
│     │  • BlacklistChecker: 客户过滤                                    │     │
│     │  • EmailNotificationService: 同步完成通知                        │     │
│     └──────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ 使用
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         核心层 (core/)                                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │   Config   │  │ Exceptions │  │   Models   │  │  Logging   │             │
│  │ • 设置     │  │ • 异常层次 │  │ • 用户详情 │  │ • 结构化   │             │
│  │ • 定时     │  │ • 上下文   │  │ • 消息     │  │ • 指标     │             │
│  │ • 环境变量 │  │ • 恢复     │  │ • 结果     │  │            │             │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘             │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │  数据库层 (database/)                                             │       │
│  │  • Schema: devices, kefus, customers, conversations, messages     │       │
│  │  • Repository: SQLite CRUD 操作                                   │       │
│  └──────────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 数据库 Schema

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   devices   │────►│    kefus    │────►│  customers  │
│  (Android   │ 1:N │  (客服账号)  │ 1:N │  (客户)     │
│   设备)     │     │             │     │             │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                   │
                           └─────────┬─────────┘
                                     │ N:1
                              ┌──────▼──────┐
                              │conversations│
                              │ (会话关联)   │
                              └──────┬──────┘
                                     │ 1:N
                              ┌──────▼──────┐     ┌─────────────┐
                              │  messages   │────►│  resources  │
                              │  (消息)     │ 1:1 │ (媒体文件)   │
                              └─────────────┘     └─────────────┘
```

### 关键设计模式

| 模式                    | 实现                                                             | 用途           |
| ----------------------- | ---------------------------------------------------------------- | -------------- |
| **Repository**          | `ConversationRepository`                                         | 数据访问抽象   |
| **Service Layer**       | `WeComService`, `FollowUpService`                                | 业务逻辑编排   |
| **Handler Chain**       | `MessageHandlers` (text, image, voice, video)                    | 可扩展消息处理 |
| **Observer**            | WebSocket 广播                                                   | 实时 UI 更新   |
| **Checkpoint/Recovery** | `SyncCheckpoint`                                                 | 可中断的长操作 |
| **Process Isolation**   | 每设备子进程；媒体目录和会话数据库默认按设备隔离，控制库保持共享 | 稳定性和并行性 |
| **TTL Cache**           | `UIStateCache`                                                   | 性能优化       |

详细架构分析请参阅 [架构审查报告](docs/05-changelog-and-upgrades/2026-02-05-architecture-review.md)。

---

## 文档

> **📚 248 个文档文件**，涵盖功能、架构、Bug 和开发指南。

### 快速链接

- **[文档索引](docs/INDEX.md)** - 完整文档概览
- **[产品功能](docs/01-product/)** - 44+ 功能规格
- **[架构与实现](docs/03-impl-and-arch/)** - 系统设计和模式
- **[Bug 和修复](docs/04-bugs-and-fixes/)** - 活跃和已解决的问题
- **[开发指南](docs/00-meta/how-we-document.md)** - 文档标准

### 文档统计

| 类别         | 文件数 | 描述               |
| ------------ | ------ | ------------------ |
| **功能**     | 45     | 产品功能和用户体验 |
| **实现**     | 74     | 架构和关键模块     |
| **Bug**      | 65     | 活跃 Bug 和修复    |
| **更新日志** | 26     | 版本历史和升级     |
| **归档**     | 26     | 已完成的任务和实验 |

详细文档请参阅 [docs/INDEX.md](docs/INDEX.md)。

---

## 测试

### 测试组织

```
tests/
├── conftest.py                    # 共享固件（模拟配置、示例数据）
├── unit/                          # 快速、隔离的测试（无需设备）
│   ├── test_config.py             # 配置加载、环境变量、默认值
│   ├── test_exceptions.py         # 异常上下文、格式化
│   ├── test_models.py             # 序列化、方法、边缘情况
│   └── test_ui_parser.py          # 解析模式、时间戳、渠道
└── integration/                   # 真实设备测试
    └── test_workflow.py           # 完整工作流执行
```

**规则**：

- ✅ 将测试放在 `tests/unit/` 或 `tests/integration/`
- ❌ 永远不要在项目根目录创建 `test_*.py`
- ❌ 永远不要在 `src/` 或 `scripts/` 中创建测试

### 运行测试

```bash
# 所有单元测试
pytest tests/unit/ -v

# 带覆盖率报告
pytest tests/unit/ --cov=src/wecom_automation --cov-report=html

# 特定测试文件
pytest tests/unit/test_ui_parser.py -v

# 集成测试（需要设备）
pytest tests/integration/ -v -m integration
```

---

## 配置

### 环境变量

```bash
export WECOM_DEVICE_SERIAL="ABC123"     # 设备序列号
export WECOM_USE_TCP="true"             # 使用 TCP 桥接
export WECOM_DEBUG="true"               # 启用调试模式
export WECOM_OUTPUT_DIR="./output"      # 输出目录
export WECOM_MAX_SCROLLS="30"           # 最大滚动尝试次数
```

### 编程配置

```python
from wecom_automation.core.config import Config

# 自定义配置
config = Config(
    device_serial="ABC123",
    debug=True,
)

# 或从环境变量
config = Config.from_env()

# 覆盖特定值
config = config.with_overrides(debug=True)
```

---

## 故障排除

| 问题            | 解决方案                                    |
| --------------- | ------------------------------------------- |
| 设备未找到      | 检查 `adb devices`，确保已启用 USB 调试     |
| UI 元素未检测到 | 增加 `--wait-after-launch`，确保设备已解锁  |
| 导入错误        | 确保 Python >= 3.11 (`python --version`)    |
| 测试失败        | 运行 `pytest tests/unit/ -v` 查看具体失败   |
| 头像捕获失败    | 确保已安装 Pillow (`uv pip install Pillow`) |

更多帮助请参阅 [Bug 和修复](docs/04-bugs-and-fixes/) 文档。

---

## 依赖

### 运行时

| 包         | 版本    | 用途         |
| ---------- | ------- | ------------ |
| `droidrun` | ≤0.4.13 | ADB 设备交互 |
| `Pillow`   | ≥10.0.0 | 头像图像处理 |

### 开发

| 包               | 版本    | 用途         |
| ---------------- | ------- | ------------ |
| `pytest`         | ≥7.0.0  | 测试框架     |
| `pytest-asyncio` | ≥0.21.0 | 异步测试支持 |
| `pytest-cov`     | ≥4.0.0  | 覆盖率报告   |

---

## 许可证

MIT

---

**项目状态**: ✅ 活跃开发中  
**最后更新**: 2026-02-05  
**版本**: 0.2.1  
**文档**: [docs/INDEX.md](docs/INDEX.md)  
**架构审查**: [docs/05-changelog-and-upgrades/2026-02-05-architecture-review.md](docs/05-changelog-and-upgrades/2026-02-05-architecture-review.md)
