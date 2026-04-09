# Git Hooks Setup

本项目使用 [Husky](https://typicode.github.io/husky/) 和 [lint-staged](https://github.com/okonet/lint-staged) 来自动化代码质量检查。

## Overview

| Hook         | 触发时机     | 检查内容                                               | 耗时  |
| ------------ | ------------ | ------------------------------------------------------ | ----- |
| `pre-commit` | 提交前       | 🔐 Secrets 扫描 + Lint + Format（仅 staged）           | < 10s |
| `commit-msg` | 提交消息验证 | 检查 Conventional Commits 格式                         | < 1s  |
| `pre-push`   | 推送前       | TypeScript 类型检查 + `tests/unit` 单测（无 coverage） | < 30s |

## 安装

```bash
# 1. 必须在仓库根目录安装依赖（Husky, lint-staged, commitlint）
#    否则 pre-commit / commit-msg 会因找不到命令而失败
npm install

# 2. 安装前端依赖（ESLint, Prettier, vue-tsc）
cd wecom-desktop && npm install && cd ..

# 3. 安装 Python 开发依赖（pytest、ruff 等；pre-push 用 uv 跑单测）
uv sync --extra dev
# 或：uv pip install -e ".[dev]"
```

安装后，`npm install` 会自动运行 `husky` 来配置 Git hooks。

**Windows 说明**：`.gitattributes` 已配置 `.husky/*` 使用 LF 换行，避免 shebang (`#!/bin/sh`) 在 Windows 下变成 `/bin/sh\r` 导致钩子无法执行。若克隆后钩子不执行，可执行 `git add --renormalize .husky` 后提交。

## Commit Message 格式

使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
type(scope): description

[optional body]

[optional footer]
```

### 可用的 Type

| Type       | 说明       | 示例                                                  |
| ---------- | ---------- | ----------------------------------------------------- |
| `feat`     | 新功能     | `feat(sync): add auto-retry on network failure`       |
| `fix`      | Bug 修复   | `fix(ui): resolve button click not responding`        |
| `docs`     | 文档更新   | `docs: update API documentation`                      |
| `style`    | 代码格式   | `style: fix indentation in utils.py`                  |
| `refactor` | 重构代码   | `refactor(parser): simplify message extraction logic` |
| `perf`     | 性能优化   | `perf: cache UI tree to reduce ADB calls`             |
| `test`     | 测试相关   | `test: add unit tests for timestamp parser`           |
| `chore`    | 维护任务   | `chore: update dependencies`                          |
| `ci`       | CI/CD 变更 | `ci: add GitHub Actions workflow`                     |
| `build`    | 构建系统   | `build: update vite config`                           |
| `revert`   | 回滚提交   | `revert: revert "feat(sync): ..."`                    |

### Scope（可选）

常用 scope：

- `sync` - 同步相关
- `followup` - Follow-up 功能
- `ui` - UI 组件
- `parser` - 解析器
- `api` - API 相关
- `db` - 数据库
- `sidecar` - Sidecar 功能

### 示例

```bash
# ✅ 正确
git commit -m "feat(sync): add support for resumable sync"
git commit -m "fix: resolve memory leak in message processor"
git commit -m "docs: update installation guide"

# ❌ 错误
git commit -m "Fixed bug"           # 没有 type
git commit -m "Feat: add feature"   # type 应该小写
git commit -m "feat: Add feature."  # 不要以句号结尾
```

## Secrets Scanning

Pre-commit 会自动扫描 staged 文件中的潜在敏感信息：

### 检测的模式

- `password = "..."`, `passwd`, `pwd`
- `api_key = "..."`, `apiKey`
- `secret_key = "..."`, `secretKey`
- `access_token = "..."`, `auth_token`
- `private_key = "..."`
- `-----BEGIN RSA PRIVATE KEY-----` (PEM keys)
- AWS credentials (`aws_access_key_id`, `aws_secret_access_key`)

### 忽略的文件

以下文件会自动跳过扫描：

- Lock 文件: `*.lock`, `package-lock.json`, `uv.lock`
- 二进制文件: `*.png`, `*.jpg`, `*.pdf`, `*.woff*`, `*.db`

### 处理误报

如果检测到误报（例如测试文件中的 mock secrets），可以：

1. **使用环境变量**：将真实密钥放在 `.env` 文件（已在 `.gitignore` 中）
2. **跳过检查**：`git commit --no-verify`（仅紧急情况）

## Linting & Formatting

### 前端 (TypeScript/Vue)

```bash
# 手动运行
cd wecom-desktop
npm run lint        # 检查
npm run lint:fix    # 检查并修复
npm run format      # 格式化
npm run typecheck   # 类型检查
```

### Python

```bash
# 手动运行
ruff check src/ wecom-desktop/backend/    # 检查
ruff check --fix src/                      # 检查并修复
ruff format src/                           # 格式化
```

## 跳过 Hooks（紧急情况）

> ⚠️ **仅在紧急情况下使用**，请确保在后续提交中修复问题。

```bash
# 跳过 pre-commit 和 commit-msg
git commit --no-verify -m "your message"

# 跳过 pre-push
git push --no-verify
```

## CI 环境

当 `CI=true` 时，所有 hooks 会自动跳过（避免在 CI 中重复运行检查）。

## 故障排除

### Hooks 没有运行

```bash
# 重新安装 Husky
npm run prepare
```

### lint-staged 卡住

```bash
# 清理 lint-staged 缓存
npx lint-staged --clear-cache
```

### commitlint 报错

检查 commit message 格式：

- 确保有 type（feat/fix/docs 等）
- type 必须小写
- 冒号后有空格
- 不要以句号结尾

### Windows 上 hooks 不执行

确保 Git 配置正确：

```bash
git config core.hooksPath .husky
```

### pre-push 上 Python 单测失败或报错

- **推荐**：安装 [uv](https://github.com/astral-sh/uv)，并在仓库根目录执行 `uv sync --extra dev`，保证 `pytest` 在 `uv run` 环境中可用。
- **运行范围**：`pre-push` 只跑根目录 `tests/unit`（快速、无设备）。`wecom-desktop/backend/tests/` 需单独或 CI 运行。
- **曾误报的 “pytest-cov / pytest 9 Windows I/O”**：常见根因是测试在**导入阶段**替换 `sys.stdout`，破坏 pytest 输出捕获；修复测试后应用 `--no-cov` 的 hook 即可稳定。详见 [Pre-push Python tests restore](../implementation/2026-04-03-pre-push-python-tests-restore.md)。

## 文件结构

```
.husky/
├── pre-commit      # 提交前检查（secrets 扫描 + lint-staged）
├── commit-msg      # 提交消息验证（commitlint）
└── pre-push        # 推送前检查（typecheck + tests）

package.json        # lint-staged 配置
commitlint.config.js # commitlint 配置
pyproject.toml      # ruff (Python) 配置
.gitattributes      # 确保 .husky/* 使用 LF 换行（Windows 兼容）

wecom-desktop/
├── .eslintrc.cjs   # ESLint 配置
├── .prettierrc     # Prettier 配置
└── .prettierignore # Prettier 忽略规则
```
