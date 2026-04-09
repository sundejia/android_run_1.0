# 文档目录规范 (Docs Organization)

## 目录结构

所有文档必须放在 `docs/` 下对应的子目录中，**禁止在 `docs/` 根目录直接放置 `.md` 文件**（仅保留 `INDEX.md` 作为总索引）。

```
docs/
├── INDEX.md                 # 总索引（唯一允许的根目录 .md）
├── analysis/                 # 分析类：流程、逻辑、时序、格式、原因分析
├── architecture/             # 架构设计
├── bugs/                     # Bug 记录与修复
├── development/              # 开发规范、Git、测试、文档规范
├── features/                 # 功能设计与实现说明（按功能/日期）
├── followup/                 # Follow-up 专题（逻辑、迁移、实现、计划）
├── guides/                   # 使用/测试指南
├── plans/                    # 改进计划、升级计划、方案
├── implementation/           # 实现总结与修复说明（非 bug、非 followup）
├── sync/                     # 同步相关（sync 流程、黑名单选择等）
├── sidecar/                  # Sidecar 相关（WebSocket、图片、跳过按钮等）
├── ai/                       # AI 提示词与回复逻辑
├── settings/                 # 设置/配置相关
└── prompts/                  # AI Agent 提示词（update_doc、agents/）
```

## 各目录说明

| 目录               | 用途                                        | 示例                                                    |
| ------------------ | ------------------------------------------- | ------------------------------------------------------- |
| **analysis**       | 流程/逻辑/时序/格式分析、根因分析           | 存储流程分析、时间戳格式、滑动日志分析                  |
| **architecture**   | 架构设计、存储设计                          | 头像存储设计                                            |
| **bugs**           | Bug 报告与修复记录                          | 按日期或 ID 命名的 bug 文档                             |
| **development**    | 开发规范、Git hooks、测试组织、文档规范     | git-hooks.md, test-organization.md                      |
| **features**       | 功能设计、实现说明、验收说明                | 按日期或功能命名的 feature 文档                         |
| **followup**       | Follow-up 全部分档：逻辑、迁移、实现、计划  | 多端实现、侧栏集成、阶段分析                            |
| **guides**         | 使用指南、测试指南、操作说明                | 历史实时测试指南、媒体下载用法                          |
| **plans**          | 改进计划、升级计划、恢复方案                | upgrade-plan-\*, universal-recovery-plan                |
| **implementation** | 实现完成总结、迁移说明、非 bug 的修复说明   | 消息去重、前端多端迁移、设置修复                        |
| **sync**           | 同步流程、黑名单选择、执行流程              | sync-execution-flow, sync-blacklist-selection           |
| **sidecar**        | Sidecar 功能：WebSocket、图片展示、跳过按钮 | sidecar_websocket_implementation                        |
| **ai**             | AI 提示词逻辑、触发与回复分析               | ai_prompt_context_logic, ai_trigger_and_prompt_analysis |
| **settings**       | 设置加载、配置迁移、重复请求修复            | `wecom-desktop/backend/services/settings/`              |
| **prompts**        | Agent 提示词与更新协议                      | prompts/agents/\*.md, prompts/update_doc.md             |

## 命名与放置规则

1. **新文档一律放入对应子目录**，根据内容选择上述目录之一。
2. **不确定时**：分析类 → `analysis/`；功能/实现 → `features/` 或 `implementation/`；计划 → `plans/`；Bug → `bugs/`。
3. **命名建议**：小写 + 连字符或下划线一致（如 `feature-name.md` 或 `feature_name.md`），含日期时可 `YYYY-MM-DD-short-name.md`。
4. **INDEX.md** 中的链接需使用相对路径，如 `followup/xxx.md`、`bugs/xxx.md`。

## 编写新文档时

- 先确定文档类型（分析 / 架构 / bug / 功能 / 计划 / 实现 / 指南 等）。
- 在 `docs/<对应目录>/` 下创建文件，不要放在 `docs/` 根目录。
- 若新增主题需要新目录，先在本文档中补充目录说明，再建目录并放入文件。

## 维护

- 增加新目录或调整归类时，更新本文档的目录结构与表格。
- INDEX.md 定期更新以反映重要文档的入口链接。
