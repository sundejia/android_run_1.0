# WeCom Automation 架构审查报告

**日期**: 2026-02-05  
**审查范围**: 整个项目代码库  
**目标**: 识别架构问题、代码规范问题，并提出改进建议

---

## 1. 项目概述

### 1.1 项目结构

```
wecom-automation/
├── src/wecom_automation/          # 核心 Python 库（自动化框架）
│   ├── cli/                       # CLI 入口
│   ├── core/                      # 核心模块（配置、异常、模型）
│   ├── database/                  # 数据库层（模型、仓库、Schema）
│   ├── services/                  # 业务服务层
│   └── utils/                     # 工具函数
├── wecom-desktop/                 # 桌面应用
│   ├── backend/                   # FastAPI 后端
│   │   ├── routers/               # API 路由
│   │   ├── services/              # 后端服务
│   │   ├── scripts/               # 可执行脚本
│   │   └── tests/                 # 后端测试
│   ├── src/                       # Vue.js 前端
│   └── electron/                  # Electron 主进程
├── tests/                         # 核心库单元测试
└── docs/                          # 项目文档
```

### 1.2 技术栈

| 层级   | 技术                                  |
| ------ | ------------------------------------- |
| 核心库 | Python 3.11+, DroidRun, ADBUtils      |
| 后端   | FastAPI, SQLite, Pydantic             |
| 前端   | Vue 3, TypeScript, Pinia, TailwindCSS |
| 桌面   | Electron, scrcpy                      |

---

## 2. 架构问题分析

### 2.1 🔴 严重问题

#### 2.1.1 代码重复：双重 BlacklistService 实现

**问题描述**:  
存在两个独立的黑名单服务实现，功能高度重叠：

```
src/wecom_automation/services/blacklist_service.py  → class BlacklistChecker
wecom-desktop/backend/services/blacklist_service.py → class BlacklistService
```

**影响**:

- 维护成本翻倍
- 逻辑不一致风险
- 缓存同步问题（已有 bug 记录）

**建议**:  
统一为单一实现，backend 通过导入 `wecom_automation` 包使用。

---

#### 2.1.2 路径硬编码问题

**问题描述**:  
项目中存在大量硬编码的相对路径计算：

```python
# 硬编码示例（45+ 处）
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
```

**统计**:

- `.parent.parent.parent` 链：45+ 处
- `sys.path.insert` 调用：33+ 处

**影响**:

- 文件移动时需要大量修改
- 容易出错且难以维护
- 不同文件层级需要不同的 `.parent` 链

**已完成的改进**:  
✅ 创建了 `utils/path_utils.py` 提供 `get_project_root()` 函数  
✅ 部分文件已迁移使用新函数

**建议**:  
继续迁移剩余文件，完全消除硬编码路径。

---

#### 2.1.3 模块边界模糊

**问题描述**:  
`wecom-desktop/backend` 与 `src/wecom_automation` 之间的职责边界不清晰：

| 功能     | wecom_automation       | backend           |
| -------- | ---------------------- | ----------------- |
| 设备管理 | DeviceDiscoveryService | device_manager.py |
| 黑名单   | BlacklistChecker       | BlacklistService  |
| 设置     | -                      | SettingsService   |
| AI 回复  | AIReplyService         | ai_analysis.py    |
| 同步     | SyncOrchestrator       | sync.py router    |

**影响**:

- 导入路径复杂
- 依赖方向不明确
- 测试困难

**建议**:  
明确分层：

- `wecom_automation`: 纯业务逻辑，无 Web 依赖
- `backend`: Web API 层，仅做路由和编排

---

### 2.2 🟡 中等问题

#### 2.2.1 大文件问题

以下文件行数过多，应考虑拆分：

| 文件                   | 行数  | 建议                                                    |
| ---------------------- | ----- | ------------------------------------------------------- |
| `wecom_service.py`     | 2940  | 拆分为 `navigation.py`, `extraction.py`, `messaging.py` |
| `sync_service.py`      | 3308  | 已有 `sync/` 子目录，迁移完成后删除旧文件               |
| `response_detector.py` | 2454  | 拆分检测逻辑和发送逻辑                                  |
| `ui_parser.py`         | 1857  | 按功能拆分（用户解析、消息解析、客服解析）              |
| `sidecar.py` (router)  | 1400+ | 拆分 WebSocket 和 HTTP 端点                             |

---

#### 2.2.2 测试目录分散

**当前结构**:

```
tests/                           # 核心库测试
  ├── unit/
  └── integration/
wecom-desktop/backend/tests/     # 后端测试
followup_test/                   # 临时测试脚本
```

**问题**:

- `followup_test/` 看起来是临时调试目录
- 后端测试与前端没有统一结构

**建议**:

1. 清理 `followup_test/`（保留有价值的测试用例，迁移到正式测试目录）
2. 统一测试命名规范

---

#### 2.2.3 配置文件分散

**当前状态**:

```
settings/
  ├── admin_actions.xlsx       # Excel 操作记录
  └── (已删除的 JSON 文件)
wecom-desktop/backend/
  └── email_settings.json      # 邮件配置
wecom_conversations.db          # SQLite 数据库
```

**问题**:

- 配置存储位置不一致
- 部分使用 JSON，部分使用数据库

**建议**:  
统一使用数据库存储配置（`settings` 表），仅保留必要的 JSON 文件用于初始引导。

---

### 2.3 🟢 轻微问题

#### 2.3.1 根目录杂乱

**根目录现有文件**:

```
image_sender_demo.py            # 演示脚本
kill-processes.bat              # Windows 批处理
restart-app.bat                 # Windows 批处理
test_ai_server.py               # 测试脚本
test_ai_server.bat              # Windows 批处理
```

**建议**:

- 移动演示脚本到 `examples/`
- 移动批处理到 `scripts/`
- 移动测试脚本到 `tests/manual/`

---

#### 2.3.2 文档结构复杂

**当前结构**:

```
docs/
├── 01-product/                  # 产品文档
├── 02-prompts-and-iterations/   # 迭代记录
├── 03-impl-and-arch/            # 实现文档
├── 04-bugs-and-fixes/           # Bug 文档
├── 05-changelog-and-upgrades/   # 变更日志
└── ai/                          # AI 相关
```

**问题**:

- 248 个文档文件，部分已过时
- 分类过于细致，查找困难

**建议**:

1. 定期归档过时文档
2. 精简分类（建议保留 4 个顶级目录）
3. 添加 `docs/index.md` 作为导航入口

---

## 3. 代码规范问题

### 3.1 命名不一致

| 类型   | 不一致示例                                      | 建议统一              |
| ------ | ----------------------------------------------- | --------------------- |
| 类名   | `BlacklistChecker` vs `BlacklistService`        | 统一为 `*Service`     |
| 文件名 | `sync_service.py` vs `device_manager.py`        | 统一为 `*_service.py` |
| 函数   | `get_kefu_name()` vs `extract_kefu_from_tree()` | 统一动词风格          |

### 3.2 导入顺序

当前状态不一致，建议使用 `isort` 或 `ruff` 强制执行：

```python
# 标准顺序
1. 标准库
2. 第三方库
3. 本地模块（绝对导入）
4. 相对导入
```

### 3.3 类型注解

**好的实践（已采用）**:

```python
async def run(options: SyncOptions) -> SyncResult:
```

**需要改进的地方**:

- 部分函数缺少返回类型注解
- 部分使用 `Any` 应该更具体

---

## 4. 依赖关系分析

### 4.1 当前依赖方向

```
┌─────────────────────────────────────────────────────────┐
│                    Electron Frontend                     │
│                      (Vue.js + Pinia)                    │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP/WebSocket
┌──────────────────────────▼──────────────────────────────┐
│                    FastAPI Backend                       │
│                   (routers + services)                   │
└───────┬──────────────────────────────────────┬──────────┘
        │ import                               │ subprocess
┌───────▼──────────────────┐     ┌─────────────▼──────────┐
│   wecom_automation       │     │    scripts/            │
│   (core library)         │     │  (initial_sync.py等)   │
└───────┬──────────────────┘     └─────────────┬──────────┘
        │                                      │ import
        └──────────────────────────────────────┘
```

### 4.2 问题：循环依赖风险

- `backend/services/` 同时导入 `wecom_automation` 和定义自己的服务
- `scripts/` 需要 `backend/` 的模块（如 `response_detector`）

### 4.3 建议依赖方向

```
Frontend → Backend → Core Library
              ↓
           Scripts (subprocess, 独立进程)
```

---

## 5. 改进建议优先级

### 5.1 P0：立即修复

| 任务                         | 影响 | 工作量 |
| ---------------------------- | ---- | ------ |
| ✅ 统一 `get_project_root()` | 高   | 已完成 |
| 合并双重 BlacklistService    | 高   | 中     |
| 清理根目录脚本               | 中   | 小     |

### 5.2 P1：短期改进

| 任务                    | 影响 | 工作量 |
| ----------------------- | ---- | ------ |
| 拆分 `wecom_service.py` | 高   | 大     |
| 清理 `followup_test/`   | 中   | 小     |
| 统一配置存储            | 中   | 中     |

### 5.3 P2：长期优化

| 任务         | 影响 | 工作量 |
| ------------ | ---- | ------ |
| 重构模块边界 | 高   | 大     |
| 拆分大文件   | 中   | 大     |
| 完善类型注解 | 中   | 中     |
| 精简文档结构 | 低   | 中     |

---

## 6. 推荐的目标架构

### 6.1 模块划分

```
wecom-automation/
├── src/wecom_automation/          # 核心库（纯 Python，无 Web 依赖）
│   ├── core/                      # 配置、异常、接口
│   ├── domain/                    # 领域模型（替代 models.py）
│   ├── infrastructure/            # 基础设施
│   │   ├── database/              # 数据库
│   │   ├── adb/                   # ADB 操作
│   │   └── external/              # 外部服务（AI、邮件）
│   ├── services/                  # 业务服务（编排层）
│   │   ├── sync/                  # 同步服务
│   │   ├── messaging/             # 消息处理
│   │   ├── navigation/            # 导航操作
│   │   └── extraction/            # 数据提取
│   └── cli/                       # CLI 入口
│
├── wecom-desktop/
│   ├── backend/                   # FastAPI 应用
│   │   ├── api/                   # API 层（仅路由）
│   │   ├── adapters/              # 适配器（调用 core library）
│   │   └── workers/               # 后台任务
│   ├── frontend/                  # Vue.js 前端
│   └── electron/                  # Electron 壳
│
├── scripts/                       # 独立可执行脚本
├── tests/                         # 统一测试目录
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── examples/                      # 示例代码
```

### 6.2 关键原则

1. **单向依赖**: `frontend → backend → core`
2. **接口隔离**: 通过接口（Protocol）解耦
3. **功能内聚**: 每个模块职责单一
4. **路径统一**: 使用 `get_project_root()` 获取路径

---

## 7. 立即可执行的改进

### 7.1 本次会话已完成

- ✅ 创建 `utils/path_utils.py`
- ✅ 迁移 12 个文件使用 `get_project_root()`
- ✅ 移动 `initial_sync.py` 和 `realtime_reply_process.py` 到 `scripts/`
- ✅ 整合 `get_kefu_name.py` 到 `utils/kefu_extraction.py`
- ✅ 删除无用的 `ai_config.json` 和相关代码
- ✅ 删除 `AdminAction` 未使用的模型
- ✅ 移除 Learning Suggestions 和 Prompt Updates 功能

### 7.2 后续建议

```bash
# 1. 清理根目录
mkdir -p examples scripts/windows
mv image_sender_demo.py examples/
mv *.bat scripts/windows/
mv test_ai_server.py tests/manual/

# 2. 清理临时测试目录
mv followup_test/ tests/legacy_followup/  # 或直接删除

# 3. 运行 linter 检查
ruff check src/ wecom-desktop/backend/ --fix
```

---

## 8. 总结

### 8.1 项目优势

- ✅ 清晰的三层架构（前端 + 后端 + 核心库）
- ✅ 良好的类型注解习惯
- ✅ 完善的文档体系
- ✅ 合理的依赖管理（pyproject.toml）
- ✅ 测试覆盖（320+ 单元测试）

### 8.2 主要改进方向

1. **代码去重**: 合并重复的服务实现
2. **文件拆分**: 处理超过 2000 行的大文件
3. **路径统一**: 完成 `get_project_root()` 迁移
4. **边界清晰**: 明确 `wecom_automation` 与 `backend` 职责

### 8.3 技术债务评估

| 类别       | 严重程度         | 预估工作量 |
| ---------- | ---------------- | ---------- |
| 代码重复   | 中               | 2-3 天     |
| 大文件拆分 | 中               | 3-5 天     |
| 路径硬编码 | 低（部分已修复） | 1 天       |
| 目录整理   | 低               | 0.5 天     |

---

_本报告由架构审查生成，建议定期（每季度）进行类似审查以跟踪技术债务。_
