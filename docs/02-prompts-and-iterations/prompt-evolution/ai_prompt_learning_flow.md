# AI 提示词学习流程详解

> **参考来源**: aliyun_webhook_demo 项目文档
> **创建日期**: 2025-12-28
> **状态**: ✅ 已实现

## 📦 实现状态

| 组件                      | 状态      | 文件                                         |
| ------------------------- | --------- | -------------------------------------------- |
| 后端 AI Config API        | ✅ 已实现 | `wecom-desktop/backend/routers/ai_config.py` |
| 后端 Admin Action API     | ✅ 已实现 | `wecom-desktop/backend/routers/ai_config.py` |
| 后端 Learning Suggestions | ✅ 已实现 | `wecom-desktop/backend/routers/ai_config.py` |
| 后端 Prompt Updates API   | ✅ 已实现 | `wecom-desktop/backend/routers/ai_config.py` |
| 前端 API 服务             | ✅ 已实现 | `wecom-desktop/src/services/api.ts`          |
| 前端设置界面              | ✅ 已实现 | `wecom-desktop/src/views/SettingsView.vue`   |
| Sidecar 操作记录          | ✅ 已实现 | `wecom-desktop/src/views/SidecarView.vue`    |

---

## 📋 概述

AI 提示词学习是一个闭环反馈系统，通过分析操作员对 AI 回复的编辑和取消行为，自动生成提示词改进建议，从而持续优化 AI 的回复质量。

### 核心目标

1. **包含对话历史** - 生成 AI 回复时包含最近的对话记录
2. **可配置系统提示词** - 全局系统提示词，可通过 UI 编辑
3. **学习循环** - 从操作员行为中学习，生成改进建议

---

## 🔄 完整流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AI 提示词学习闭环                                   │
└─────────────────────────────────────────────────────────────────────────────┘

                                    ┌──────────────┐
                                    │   用户消息    │
                                    └──────┬───────┘
                                           │
                                           ▼
                              ┌────────────────────────┐
                              │   Context Builder      │
                              │   构建 AI 上下文        │
                              │  ┌──────────────────┐  │
                              │  │ system_prompt    │  │
                              │  │ history (N条)   │  │
                              │  │ current_message  │  │
                              │  └──────────────────┘  │
                              └────────────┬───────────┘
                                           │
                                           ▼
                              ┌────────────────────────┐
                              │     AI 服务器          │
                              │   生成回复              │
                              └────────────┬───────────┘
                                           │
                                           ▼
                              ┌────────────────────────┐
                              │   待审批消息队列        │
                              │   (10秒倒计时)         │
                              └────────────┬───────────┘
                                           │
                     ┌─────────────────────┼─────────────────────┐
                     │                     │                     │
                     ▼                     ▼                     ▼
              ┌──────────┐          ┌──────────┐          ┌──────────┐
              │  批准 ✅  │          │  编辑 ✏️  │          │  取消 ❌  │
              │ Approve  │          │   Edit   │          │  Cancel  │
              └──────────┘          └────┬─────┘          └────┬─────┘
                                         │                     │
                                         │    记录原因          │    记录原因
                                         ▼                     ▼
                              ┌────────────────────────────────────┐
                              │         AdminAction 表              │
                              │  ┌──────────────────────────────┐  │
                              │  │ action_type: EDIT/CANCEL     │  │
                              │  │ original_content: 原始内容   │  │
                              │  │ modified_content: 修改后内容 │  │
                              │  │ reason: 操作原因             │  │
                              │  │ created_at: 时间戳           │  │
                              │  └──────────────────────────────┘  │
                              └────────────────┬───────────────────┘
                                               │
                                               │ 聚合分析
                                               ▼
                              ┌────────────────────────────────────┐
                              │     Learning Suggestions           │
                              │     学习建议聚合器                   │
                              │  ┌──────────────────────────────┐  │
                              │  │ 统计: edit_count, cancel_count│  │
                              │  │ 分析: avg_length_delta       │  │
                              │  │ 主题: 提取常见原因关键词      │  │
                              │  │ 生成: suggested_prompt_snippet│  │
                              │  └──────────────────────────────┘  │
                              └────────────────┬───────────────────┘
                                               │
                                               ▼
                              ┌────────────────────────────────────┐
                              │         操作员审核                  │
                              │  ┌──────────────────────────────┐  │
                              │  │ 查看建议                      │  │
                              │  │ 选择策略: append / replace   │  │
                              │  │ 应用或忽略                    │  │
                              │  └──────────────────────────────┘  │
                              └────────────────┬───────────────────┘
                                               │
                                               │ 应用建议
                                               ▼
                              ┌────────────────────────────────────┐
                              │         System Prompt 更新         │
                              │  ┌──────────────────────────────┐  │
                              │  │ 记录 PromptUpdate 审计        │  │
                              │  │ 更新 SystemSetting           │  │
                              │  │ 广播到所有客户端              │  │
                              │  └──────────────────────────────┘  │
                              └────────────────────────────────────┘
                                               │
                                               │ 循环
                                               └──────────────────────────────┐
                                                                              │
                                    ┌──────────────────────────────────────────┘
                                    │
                                    ▼
                              ┌──────────────┐
                              │  下一条消息   │  ──────► 使用更新后的提示词
                              └──────────────┘
```

---

## 🏗️ 架构组件

### 1. Context Builder（上下文构建器）

**文件**: `utils/ai_context.py`

**功能**: 为 AI 请求构建完整的上下文

```python
def build_ai_context(user_id: str, current_text: str, base_ctx: dict) -> dict:
    """
    构建 AI 上下文

    返回:
    {
        "system_prompt": "系统提示词...",
        "conversation_history": [
            {"role": "user", "content": "用户消息1"},
            {"role": "assistant", "content": "AI回复1"},
            ...
        ],
        "current_message": "当前用户消息"
    }
    """
```

**输出格式（嵌入到消息文本）**:

```
[SYSTEM]
你是一个友好的客服助手...

[CONTEXT]
USER: 你好，我想咨询一下...
ASSISTANT: 您好！很高兴为您服务...
USER: 我的订单号是...
ASSISTANT: 好的，让我帮您查询...

[LATEST USER]
订单什么时候能到？
```

### 2. AI Client（AI 客户端）

**文件**: `utils/ai_client.py`

**功能**: 将构建的上下文发送到 AI 服务器

```python
class AIClient:
    async def generate_reply(self, context: dict) -> str:
        """
        发送请求到 AI 服务器

        日志输出:
        🤖 AI-PAYLOAD-SUMMARY: system=True turns=5 size=1234
        """
```

### 3. Learning Suggestions（学习建议聚合器）

**文件**: `utils/learning/suggestions.py`

**功能**: 分析操作员行为，生成改进建议

```python
class SuggestionsAggregator:
    def aggregate(self, admin_actions: List[AdminAction]) -> dict:
        """
        分析最近的编辑/取消操作

        返回:
        {
            "stats": {
                "edit_count": 5,      # 编辑次数
                "cancel_count": 2,    # 取消次数
                "avg_length_delta": -15.3  # 平均长度变化（负数表示缩短）
            },
            "themes": ["太长", "跑题", "语气不对"],  # 常见原因主题
            "suggested_prompt_snippet": "回复要简洁，控制在50字以内。避免偏离主题。"
        }
        """
```

---

## 📊 数据模型

### SystemSetting 表

存储系统配置（包括 system_prompt）

```sql
CREATE TABLE system_setting (
    key TEXT PRIMARY KEY,
    value TEXT,           -- JSON 或纯文本
    updated_at TIMESTAMP,
    updated_by TEXT
);

-- 示例数据
INSERT INTO system_setting VALUES
('system_prompt', '你是一个友好的客服助手...', '2025-01-01 10:00:00', 'admin'),
('history_window', '10', '2025-01-01 10:00:00', 'admin');
```

### AdminAction 表

记录操作员的编辑/取消操作

```sql
CREATE TABLE admin_action (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    action_type TEXT,      -- 'EDIT', 'CANCEL', 'APPROVE'
    original_content TEXT, -- 原始 AI 回复
    modified_content TEXT, -- 编辑后内容（仅 EDIT）
    reason TEXT,           -- 操作原因
    admin_id TEXT,
    created_at TIMESTAMP
);
```

### PromptUpdate 表（审计日志）

记录提示词的每次更新

```sql
CREATE TABLE prompt_update (
    id TEXT PRIMARY KEY,
    snippet TEXT,          -- 应用的建议片段
    strategy TEXT,         -- 'append' 或 'replace'
    applied_by TEXT,       -- 操作员 ID
    previous_prompt TEXT,  -- 更新前的提示词
    new_prompt TEXT,       -- 更新后的提示词
    created_at TIMESTAMP,
    applied_at TIMESTAMP
);
```

---

## 🔌 API 端点

### 1. 配置管理

#### GET /monitoring/a../03-impl-and-arch/key-modules/config

获取当前 AI 配置

**响应**:

```json
{
  "success": true,
  "config": {
    "system_prompt": "你是一个友好的客服助手...",
    "history_window": 10
  },
  "updated_at": "2025-01-01T10:00:00"
}
```

#### POST /monitoring/a../03-impl-and-arch/key-modules/config

更新 AI 配置

**请求**:

```json
{
  "system_prompt": "新的系统提示词...",
  "history_window": 7
}
```

### 2. 学习建议

#### GET /monitoring/a../03-impl-and-arch/key-modules/learning/suggestions

获取基于操作员行为的改进建议

**响应**:

```json
{
  "success": true,
  "data": {
    "stats": {
      "edit_count": 5,
      "cancel_count": 2,
      "avg_length_delta": -15.3
    },
    "suggested_prompt_snippet": "回复要简洁，控制在50字以内。保持专业语气。"
  }
}
```

### 3. 应用建议

#### POST /monitoring/a../03-impl-and-arch/key-modules/prompt/apply

应用建议到系统提示词

**请求**:

```json
{
  "snippet": "回复要简洁，控制在50字以内。",
  "strategy": "append", // 或 "replace"
  "applied_by": "operator_001"
}
```

**响应**:

```json
{
  "success": true,
  "config": {
    "system_prompt": "你是一个友好的客服助手...\n\n回复要简洁，控制在50字以内。",
    "history_window": 10
  },
  "update": {
    "id": "update_123",
    "strategy": "append",
    "applied_by": "operator_001",
    "applied_at": "2025-01-01T11:00:00"
  }
}
```

### 4. 更新历史

#### GET /monitoring/a../03-impl-and-arch/key-modules/prompt/updates

获取提示词更新历史

**响应**:

```json
{
  "success": true,
  "count": 3,
  "updates": [
    {
      "id": "update_123",
      "strategy": "append",
      "applied_by": "operator_001",
      "created_at": "2025-01-01T11:00:00",
      "snippet_preview": "回复要简洁..."
    }
  ]
}
```

#### POST /monitoring/a../03-impl-and-arch/key-modules/prompt/revert

回滚到之前的提示词版本

**请求**:

```json
{
  "update_id": "update_123"
}
```

---

## 🖥️ UI 界面

### AI 设置面板

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚙️ AI Settings                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  System Prompt                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 你是一个友好的客服助手，请用中文回复用户的问题。          │  │
│  │ 回复要简洁明了，控制在100字以内。                        │  │
│  │ 如果用户要求转人工，请直接回复"转人工"。                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  History Window: [10] (0-50 条历史消息)                         │
│                                                                 │
│  Last Updated: 2025-01-01 10:00:00                              │
│                                                                 │
│  [💾 Save]  [🔄 Reset]                                          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  📊 Learning Suggestions                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Recent Stats:                                                  │
│  • Edits: 5  • Cancels: 2  • Avg Length Change: -15 chars      │
│                                                                 │
│  Suggested Improvement:                                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 回复要更简洁，避免重复信息。保持专业但友好的语气。        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  [📝 Append to Prompt]  [🔄 Replace Prompt]  [❌ Ignore]        │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  📜 Update History                                              │
├─────────────────────────────────────────────────────────────────┤
│  • 2025-01-01 11:00 - append - "回复要简洁..." [↩️ Revert]     │
│  • 2024-12-30 15:30 - append - "保持专业..." [↩️ Revert]       │
│  • 2024-12-28 09:15 - replace - "完整提示词..." [↩️ Revert]    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📈 学习算法

### 建议生成逻辑

```python
def generate_suggestions(admin_actions: List[AdminAction]) -> dict:
    """
    分析最近 N 条操作员操作，生成改进建议
    """

    # 1. 统计基础数据
    edits = [a for a in admin_actions if a.action_type == 'EDIT']
    cancels = [a for a in admin_actions if a.action_type == 'CANCEL']

    stats = {
        "edit_count": len(edits),
        "cancel_count": len(cancels),
        "avg_length_delta": calculate_avg_length_change(edits)
    }

    # 2. 提取原因关键词
    all_reasons = [a.reason for a in admin_actions if a.reason]
    themes = extract_common_themes(all_reasons)
    # 例如: ["太长", "语气不对", "信息不准确"]

    # 3. 分析编辑模式
    patterns = analyze_edit_patterns(edits)
    # 例如: 删除了问候语、缩短了回复、添加了具体信息

    # 4. 生成建议片段
    snippet_parts = []

    if stats["avg_length_delta"] < -10:
        snippet_parts.append("回复要更简洁")

    if "语气" in themes:
        snippet_parts.append("保持专业友好的语气")

    if "跑题" in themes:
        snippet_parts.append("回答要紧扣用户问题")

    suggested_snippet = "。".join(snippet_parts) + "。" if snippet_parts else ""

    return {
        "stats": stats,
        "themes": themes,
        "suggested_prompt_snippet": suggested_snippet
    }
```

---

## 🔧 实施步骤（当前项目已实现）

### Phase 1: 数据收集 ✅

1. [x] 创建 `AdminAction` JSON 存储（`settings/admin_actions.json`）
2. [x] 在编辑/取消操作时记录原因（SidecarView.vue）
3. [x] Sidecar 自动记录操作（发送=批准/编辑，取消=取消）

### Phase 2: 配置 API ✅

1. [x] 创建 AI 配置 JSON 存储（`settings/ai_config.json`）
2. [x] 实现 `GET/POST /a../03-impl-and-arch/key-modules/config` 端点
3. [x] 前端添加配置界面（SettingsView.vue）

### Phase 3: 学习聚合 ✅

1. [x] 实现学习建议聚合算法（`ai_config.py`）
2. [x] 实现 `GET /a../03-impl-and-arch/key-modules/learning/suggestions` 端点
3. [x] 前端显示建议和统计

### Phase 4: 应用和审计 ✅

1. [x] 创建 `PromptUpdate` JSON 存储（`settings/prompt_updates.json`）
2. [x] 实现 `POST /a../03-impl-and-arch/key-modules/prompt/apply` 端点
3. [x] 实现 `POST /a../03-impl-and-arch/key-modules/prompt/revert` 端点
4. [x] 前端添加应用/回滚按钮

### Phase 5: 测试和优化

1. [ ] 编写单元测试
2. [ ] 端到端测试
3. [ ] 优化建议生成算法

---

## 📝 关键配置

```yaml
ai:
  # 系统提示词（存储在数据库）
  default_system_prompt: '你是一个友好的客服助手...'

  # 历史窗口大小（包含多少条历史消息）
  history_window: 10 # 0-50，0 表示禁用

  # 学习设置
  learning:
    enabled: true
    min_actions_for_suggestion: 5 # 至少 5 条操作才生成建议
    suggestion_refresh_interval: 3600 # 每小时刷新建议
```

---

## 🔗 相关文件（当前项目）

| 组件                | 当前项目文件                                 |
| ------------------- | -------------------------------------------- |
| 后端 AI Config API  | `wecom-desktop/backend/routers/ai_config.py` |
| 后端主入口          | `wecom-desktop/backend/main.py`              |
| 前端 API 服务       | `wecom-desktop/src/services/api.ts`          |
| 前端设置界面        | `wecom-desktop/src/views/SettingsView.vue`   |
| 前端 Sidecar        | `wecom-desktop/src/views/SidecarView.vue`    |
| 设置存储            | `wecom-desktop/src/stores/settings.ts`       |
| AI 配置存储         | `settings/ai_config.json`                    |
| Admin Actions 存储  | `settings/admin_actions.json`                |
| Prompt Updates 存储 | `settings/prompt_updates.json`               |

---

## 📚 测试用例

```python
# test_ai_context_builder.py
def test_builds_history_with_last_n_messages():
    """历史记录应包含最近 N 条消息"""

# test_ai_config_api.py
def test_get_returns_default_config():
    """GET 应返回默认配置"""

def test_post_updates_and_persists():
    """POST 应更新并持久化配置"""

# test_learning_suggestions.py
def test_generates_suggestions_from_edits():
    """应从编辑操作生成建议"""

def test_includes_reason_themes():
    """建议应包含原因主题"""

# test_apply_prompt_api.py
def test_append_strategy():
    """append 策略应追加到现有提示词"""

def test_replace_strategy():
    """replace 策略应替换现有提示词"""

def test_creates_audit_record():
    """应创建审计记录"""
```
