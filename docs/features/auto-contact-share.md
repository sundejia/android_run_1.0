# Auto Contact Share (自动推送主管名片)

> **状态**: 已实现  
> **日期**: 2026-04-30  
> **关联**: [Media Auto-Actions](media-auto-actions.md) — 第三個注冊到 MediaEventBus 的 IMediaAction

## 功能概述

当客户在会话中发送图片或视频后，系统可按配置自动向该客户推送主管（或指定联系人）的企业微信名片（Work Card）。

- 支持按客服(kefu)配置不同主管（`kefu_overrides` 映射），未配置则 fallback 到全局 `contact_name`
- 与 review-gate 审核门控无缝集成：开启审核时需审核通过才推送；关闭时直接推送
- 幂等表保证每个客户只推一次
- 同步 + 实时监控两条链路均触发

## UI 自动化流程（真机验证）

在 720×1612 分辨率设备上验证通过的完整流程：

```
1. navigate_to_chat(customer)           → WeComService
2. tap i9u (附件按钮, 右下角)           → 打开附件面板
3. find "Contact Card" (自适应)          → 先查当前页，未找到则左滑 GridView 再查
4. tap ndb (搜索按钮, 右上角第二)        → 打开搜索输入框
5. input contact_name → select result   → 搜索并选中联系人
6. tap "Send" (dak/blz)                → 确认发送
```

### 自适应页查找

WeCom 会将最近使用过的附件选项提升到第一页。`_open_contact_card_menu()` 实现了自适应逻辑：

1. 先尝试在当前页查找 "Contact Card" 并点击（快速路径）
2. 若未找到，左滑 GridView (`ahe`) 到下一页再重试（慢速路径）

**重要**：Contact Card 的匹配使用**文本精确匹配**（"Contact Card" / "名片" / "Personal Card"），不能用 resourceId `aha` —— `aha` 是附件面板中所有项目标签共用的 resourceId（Image、Camera、Contact Card 等的标签 rid 均为 `aha`）。

### 联系人选择器搜索（SearchContactFinder）

选择器打开后有两种联系人定位策略：

1. **ScrollContactFinder**（旧）：滚动列表，按文本前缀匹配 — 适合联系人少的场景
2. **SearchContactFinder**（新）：点击搜索按钮 → 输入搜索词 → 从结果中匹配 — 适合联系人多的场景

搜索流程：

1. 点击右上角第二按钮 `ndb` 打开搜索输入框（EditText, rid `lba`）
2. 输入联系人名称，等待结果列表刷新
3. 在搜索输入框下方区域匹配结果（排除 EditText 本身）
4. 选中第一个匹配项

**注意**：不要点击 `nd7`（最右上角）——那是关闭/返回按钮，会关闭整个选择器。

### 真机 Resource ID 映射

| 步骤 | ResId | Text | 说明 |
|------|-------|------|------|
| 附件按钮 | `i9u` | — | 聊天输入区最右侧图标 |
| 附件菜单 GridView | `ahe` | — | 需左滑翻到第二页 |
| 名片菜单项 | `aha` | "Contact Card" | 第二页，**必须用文本匹配**（aha 为所有标签共用） |
| 选择器标题 | `nca` | "Select Contact(s)" | — |
| 选择器列表 | `cth` | — | ListView |
| **搜索按钮** | `ndb` | — | 右上角第二按钮（⚠️ 不是 nd7） |
| 搜索输入框 | `lba` | "Search" | 点击 ndb 后出现的 EditText |
| 确认发送 | `dak` / `blz` / `i_2` | "Send" / "SEND" | 确认对话框，大小写均可 |
| 取消 | `dah` | "Cancel" | 确认对话框 |

## 架构

```
客户发送图片/视频
    ↓
MessageProcessor._maybe_emit_media_event()
    ↓
[review-gate 开启] → pending_reviews → rating-server → webhook → ReviewGate
[review-gate 关闭] → 直接 emit
    ↓
MediaEventBus.emit(event, settings)
    ↓
AutoContactShareAction.should_execute()
  ├── 全局 enabled
  ├── auto_contact_share.enabled
  ├── event.is_media
  ├── _resolve_contact_name(event, settings)  ← kefu_overrides 优先
  └── 幂等检查: contact_already_shared()
    ↓
AutoContactShareAction.execute()
  ├── ContactShareService.share_contact_card()
  │     ├── navigate_to_chat()
  │     ├── _tap_attach_button()
  │     ├── _swipe_attach_page2()
  │     ├── _tap_contact_card_menu()
  │     ├── _select_contact_from_picker(contact_name)
  │     ├── _confirm_send()
  │     └── _record_share()  ← 写入幂等表
  └── finally: restore_navigation()  ← 必定恢复私聊列表
```

## 设置结构

类别 `media_auto_actions`，键 `auto_contact_share`：

```json
{
  "auto_contact_share": {
    "enabled": false,
    "contact_name": "",
    "skip_if_already_shared": true,
    "cooldown_seconds": 0,
    "kefu_overrides": {
      "客服A": "主管X",
      "客服B": "主管Y"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | boolean | 功能开关 |
| `contact_name` | string | 全局默认主管名（精确匹配联系人选择器中的显示名前缀） |
| `skip_if_already_shared` | boolean | 幂等：已推过则跳过 |
| `cooldown_seconds` | int | 冷却时间（预留，当前为 0 = 仅推一次） |
| `kefu_overrides` | object | 按客服配置不同主管，key 为 kefu_name |

## 数据库

幂等表 `media_action_contact_shares`（在 effects DB 中按需创建）：

```sql
CREATE TABLE IF NOT EXISTS media_action_contact_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    kefu_name TEXT DEFAULT '',
    status TEXT DEFAULT 'shared',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_contact_shares_lookup
    ON media_action_contact_shares (device_serial, customer_name, contact_name);
```

## 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/wecom_automation/services/contact_share/__init__.py` | 模块导出 |
| `src/wecom_automation/services/contact_share/models.py` | `ContactShareRequest`, `ContactShareResult` |
| `src/wecom_automation/services/contact_share/selectors.py` | UI 元素关键词（真机验证） |
| `src/wecom_automation/services/contact_share/service.py` | `IContactShareService` + `ContactShareService` |
| `src/wecom_automation/services/ui_search/__init__.py` | ui_search 模块导出 |
| `src/wecom_automation/services/ui_search/selectors.py` | 选择器搜索 UI 关键词（含 ndb） |
| `src/wecom_automation/services/ui_search/ui_helpers.py` | 纯函数：bounds 解析、布局排序、搜索按钮/输入框/结果匹配 |
| `src/wecom_automation/services/ui_search/strategy.py` | `ScrollContactFinder` + `SearchContactFinder` 策略模式 |
| `src/wecom_automation/services/media_actions/actions/auto_contact_share.py` | `AutoContactShareAction` |
| `tests/unit/test_auto_contact_share_action.py` | 23 个单元测试 |
| `tests/unit/test_ui_search_helpers.py` | ui_helpers 单元测试 |
| `tests/unit/test_contact_finder_strategy.py` | ContactFinder 策略单元测试 |
| `tests/integration/test_contact_search_e2e.py` | 真机端到端测试（8 步流程） |

### 修改

| 文件 | 说明 |
|------|------|
| `src/wecom_automation/services/media_actions/settings_loader.py` | 添加 `auto_contact_share` 默认值 + 合并逻辑 |
| `src/wecom_automation/services/media_actions/factory.py` | 注册 `AutoContactShareAction` |

## 测试

| 范围 | 路径 |
|------|------|
| Action 单元测试 | `tests/unit/test_auto_contact_share_action.py` |
| UI 搜索辅助函数 | `tests/unit/test_ui_search_helpers.py` |
| 联系人查找策略 | `tests/unit/test_contact_finder_strategy.py` |
| 事件总线 + 工厂 | `tests/unit/test_media_actions_factory.py`（已更新：3 个 action） |
| 设置加载 | `tests/unit/test_media_actions_settings_loader.py` |
| **真机端到端** | `tests/integration/test_contact_search_e2e.py`（需设备连接） |

## 注意事项

- `contact_name` 支持双向子串匹配：联系人文本包含搜索词，或搜索词包含联系人文本均可
- 附件菜单默认显示第一页（Image/Camera 等必须左滑才能看到 Contact Card）
- 名片菜单项匹配**必须用文本**，不能用 resourceId `aha`（所有附件标签共用）
- 联系人选择器中，搜索按钮是 `ndb`（右上第二），**不是** `nd7`（最右上，关闭按钮）
- 搜索时 `screen_width` 必须使用设备实际分辨率（默认 1080 会导致左边界过滤错误）
- `restore_navigation()` 在 `finally` 块中调用，保证即使 UI 自动化中途失败也会恢复到私聊列表
- 与 `AutoGroupInviteAction` 和 `AutoBlacklistAction` 并行运行在同一个 `MediaEventBus` 上，单动作异常不阻塞其他动作
