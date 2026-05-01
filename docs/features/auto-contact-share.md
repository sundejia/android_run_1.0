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

在 720×1612 分辨率设备上验证通过的 5 步流程：

```
1. navigate_to_chat(customer)           → WeComService
2. tap i9u (附件按钮, 右下角)           → 打开附件面板
3. find "Contact Card" (自适应)          → 先查当前页，未找到则左滑 GridView 再查
4. select contact (text 前缀匹配)        → 在联系人选择器中匹配
5. tap "Send" (dak)                     → 确认发送
```

### 自适应页查找

WeCom 会将最近使用过的附件选项提升到第一页。`_open_contact_card_menu()` 实现了自适应逻辑：

1. 先尝试在当前页查找 "Contact Card" 并点击（快速路径）
2. 若未找到，左滑 GridView (`ahe`) 到下一页再重试（慢速路径）

这确保了首次使用和后续使用两种场景都能正常工作。

### 真机 Resource ID 映射

| 步骤 | ResId | Text | 说明 |
|------|-------|------|------|
| 附件按钮 | `i9u` | — | 聊天输入区最右侧图标 |
| 附件菜单 GridView | `ahe` | — | 需左滑翻到第二页 |
| 名片菜单项 | `aha` | "Contact Card" | 第二页第一列 |
| 选择器标题 | `nca` | "Select Contact(s)" | — |
| 联系人列表 | `cth` | — | ListView |
| 确认发送 | `dak` | "Send" | 确认对话框 |
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
| `src/wecom_automation/services/media_actions/actions/auto_contact_share.py` | `AutoContactShareAction` |
| `tests/unit/test_auto_contact_share_action.py` | 23 个单元测试 |

### 修改

| 文件 | 说明 |
|------|------|
| `src/wecom_automation/services/media_actions/settings_loader.py` | 添加 `auto_contact_share` 默认值 + 合并逻辑 |
| `src/wecom_automation/services/media_actions/factory.py` | 注册 `AutoContactShareAction` |

## 测试

| 范围 | 路径 |
|------|------|
| Action 单元测试 | `tests/unit/test_auto_contact_share_action.py` |
| 事件总线 + 工厂 | `tests/unit/test_media_actions_factory.py`（已更新：3 个 action） |
| 设置加载 | `tests/unit/test_media_actions_settings_loader.py` |

## 注意事项

- `contact_name` 必须与联系人选择器中的显示名**前缀精确匹配**（如 "陈新宇2-滨"）
- 附件菜单默认显示第一页（Image/Camera 等必须左滑才能看到 Contact Card）
- `restore_navigation()` 在 `finally` 块中调用，保证即使 UI 自动化中途失败也会恢复到私聊列表
- 与 `AutoGroupInviteAction` 和 `AutoBlacklistAction` 并行运行在同一个 `MediaEventBus` 上，单动作异常不阻塞其他动作
