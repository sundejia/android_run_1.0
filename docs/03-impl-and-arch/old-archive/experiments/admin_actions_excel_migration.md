# Admin Actions 存储格式修改计划

> 时间: 2026-01-18  
> 状态: ✅ 已实施

---

## 目标

将操作员行为记录从 JSON 格式改为 Excel 格式，并增加对话上下文信息。

---

## 当前状态

### 存储位置

- 文件: `settings/admin_actions.json`

### 当前数据结构

```json
{
  "id": "ac2fe7c4-1000-4eef-9eef-8ff45988ca96",
  "message_id": "sidecar_320125365403_1766912626125",
  "action_type": "EDIT", // APPROVE | EDIT | CANCEL
  "original_content": "原始消息",
  "modified_content": "修改后消息", // 仅 EDIT 时有值
  "reason": "操作员编辑了AI回复",
  "admin_id": "sidecar_operator",
  "serial": "320125365403",
  "customer_name": "李衡",
  "created_at": "2025-12-28T17:03:46.128496"
}
```

### 相关代码

- `wecom-desktop/backend/routers/ai_config.py`
  - `save_admin_actions()` - 保存操作记录
  - `load_admin_actions()` - 加载操作记录

---

## 修改需求

### 1. 存储格式变更

| 修改项   | 当前                          | 目标                          |
| -------- | ----------------------------- | ----------------------------- |
| 文件格式 | JSON                          | Excel (.xlsx)                 |
| 文件路径 | `settings/admin_actions.json` | `settings/admin_actions.xlsx` |

### 2. 过滤规则

| 操作类型         | 是否保存  |
| ---------------- | --------- |
| `APPROVE` (批准) | ❌ 不保存 |
| `EDIT` (编辑)    | ✅ 保存   |
| `CANCEL` (取消)  | ✅ 保存   |

### 3. 新增字段

需要在记录时获取并保存对话上下文（最近 4 条消息）。

---

## Excel 格式设计

根据截图，Excel 表格结构如下：

| 列  | 字段名 | 说明                                        |
| --- | ------ | ------------------------------------------- |
| A   | 序号   | 自增序号                                    |
| B   | 分类   | 问题分类标签（如"问题1"、"时间确认"等）     |
| C   | 发送者 | 上文1发送者 (客服名称 或 客户ID)            |
| D   | 上文1  | 对话历史第1条消息内容                       |
| E   | 发送者 | 上文2发送者                                 |
| F   | 上文2  | 对话历史第2条消息内容                       |
| G   | 发送者 | 上文3发送者                                 |
| H   | 上文3  | 对话历史第3条消息内容                       |
| I   | 发送者 | 上文4发送者                                 |
| J   | 上文4  | 对话历史第4条消息内容                       |
| K   | 发送者 | 问题发送者 (客户ID)                         |
| L   | 问题   | 客户最新消息，AI 需要回复的问题             |
| M   | 回复   | **用户修改后的回复内容** (modified_content) |

### 字段说明

- **上文1-4**: 对话上下文，从旧到新排列，包含客服和客户的对话记录
- **发送者**: 可以是客服名称（如"李婉莹"）或客户ID（如"B2503270775"）
- **问题 (L列)**: 客户发送的最新消息，这是 AI 需要回复的问题
- **回复 (M列)**: 用户在 Sidecar 界面修改后的最终发送内容，这是训练数据的核心

---

## 实施计划

### 阶段 1: 添加依赖

在后端添加 Excel 操作库：

```bash
pip install openpyxl
```

### 阶段 2: 修改数据模型

修改 `RecordAdminActionRequest`，添加上下文字段：

```python
class RecordAdminActionRequest(BaseModel):
    message_id: str
    action_type: str  # APPROVE, EDIT, CANCEL
    original_content: str
    modified_content: Optional[str] = None
    reason: str
    serial: str
    customer_name: str
    # 新增字段
    context: Optional[List[dict]] = None  # 对话上下文
```

### 阶段 3: 修改前端

在 Sidecar 发送消息时，传递对话上下文：

修改 `SidecarView.vue` 的 `recordAdminAction` 调用，添加 `context` 参数。

### 阶段 4: 修改后端存储逻辑

修改 `ai_config.py`:

```python
from openpyxl import Workbook, load_workbook
from pathlib import Path

ADMIN_ACTIONS_EXCEL = SETTINGS_DIR / "admin_actions.xlsx"

def save_admin_action_to_excel(action: Dict) -> None:
    """保存单条操作记录到 Excel"""
    # 过滤批准操作
    if action.get("action_type") == "APPROVE":
        return

    # 创建或加载工作簿
    if ADMIN_ACTIONS_EXCEL.exists():
        wb = load_workbook(ADMIN_ACTIONS_EXCEL)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        # 写入表头
        headers = ["序号", "分类", "发送者", "上文1", "发送者", "上文2",
                   "发送者", "上文3", "发送者", "上文4", "发送者",
                   "问题", "回复"]
        ws.append(headers)

    # 解析上下文
    context = action.get("context", [])

    # 构建行数据
    row_num = ws.max_row
    row = [
        row_num,  # 序号
        action.get("action_type"),  # 分类
    ]

    # 添加上下文（最多4条）
    for i in range(4):
        if i < len(context):
            msg = context[i]
            sender = action.get("customer_name") if not msg.get("is_from_kefu") else "客服"
            content = msg.get("content", "")
        else:
            sender = ""
            content = ""
        row.extend([sender, content])

    # 问题发送者 (客户ID)
    row.append(action.get("customer_id", ""))
    # 问题 = 客户最新消息
    row.append(action.get("customer_message", ""))
    # 回复 = 用户修改后的内容
    row.append(action.get("modified_content", ""))

    ws.append(row)
    wb.save(ADMIN_ACTIONS_EXCEL)
```

### 阶段 5: 更新 API 端点

修改 `record_admin_action` 函数：

```python
@router.post("/admin-action")
async def record_admin_action(request: RecordAdminActionRequest):
    # 过滤批准操作
    if request.action_type == "APPROVE":
        return {"success": True, "message": "Approve actions are not recorded"}

    action = {
        "action_type": request.action_type,
        "original_content": request.original_content,
        "modified_content": request.modified_content,
        "customer_name": request.customer_name,
        "context": request.context or [],
        # ... 其他字段
    }

    save_admin_action_to_excel(action)
    return {"success": True}
```

---

## 修改文件清单

| 文件                                         | 修改内容                 |
| -------------------------------------------- | ------------------------ |
| `wecom-desktop/backend/routers/ai_config.py` | 修改存储逻辑，使用 Excel |
| `wecom-desktop/src/views/SidecarView.vue`    | 传递对话上下文到 API     |
| `wecom-desktop/src/services/api.ts`          | 更新请求接口类型         |
| `requirements.txt`                           | 添加 openpyxl 依赖       |

---

## 旧数据处理

1. 保留 `admin_actions.json` 作为历史备份
2. 新记录写入 `admin_actions.xlsx`
3. 可选：提供迁移脚本将 JSON 转换为 Excel

---

## 注意事项

1. **并发写入**: Excel 文件不支持高并发写入，需要添加文件锁
2. **文件大小**: Excel 有行数限制（约100万行），需要考虑定期归档
3. **编码问题**: 确保中文内容正确保存
