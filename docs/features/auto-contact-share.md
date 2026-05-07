# Auto Contact Share (自动推送主管名片)

> **状态**: 已实现（持续按机型 / WeCom 版本演进）  
> **日期**: 2026-04-30（初版）；**关键可靠性修订**: 2026-05-06 ~ 2026-05-07  
> **关联**: [Media Auto-Actions](media-auto-actions.md) — 第三个注册到 MediaEventBus 的 `IMediaAction`  
> **实现备忘**: [Contact share reliability (2026-05)](../implementation/2026-05-07-contact-share-reliability.md)

## 功能概述

当客户在会话中发送图片或视频后，系统可按配置自动向该客户推送主管（或指定联系人）的企业微信名片（Work Card）。

- 支持按客服(kefu)配置不同主管（`kefu_overrides` 映射），未配置则 fallback 到全局 `contact_name`
- 与 review-gate 审核门控无缝集成：开启审核时需审核通过才推送；关闭时直接推送
- 幂等表保证每个客户只推一次（配置允许时）
- 同步 + 实时监控两条链路均可触发
- **可选**：发送名片前先发送一段话术；若名片流程失败且已发送话术，可发送**兜底话术**（见 `ContactShareRequest.recovery_message_on_failure_text` 与实现）

## UI 自动化流程（真机验证 + 多版本兼容）

在 **720×1612** 等设备上验证；不同 WeCom build 的 `resourceId` 可能不同，下列 ID **均为 append-only 列表中的观测值**，旧机型保留旧 token。

```
1. navigate_to_chat(customer)           → WeComService
2. _tap_attach_button()               → 匹配 ATTACH_RESOURCE_PATTERNS（如 i9u / id8 / igu）或位置启发式
3. _assert_page_state(attach_panel)   → PageStateValidator：确认附件面板已打开
4. _open_contact_card_menu()          → 当前页精确匹配 Contact Card 文案；否则 _swipe_attach_grid() 后重试
5. _assert_page_state(contact_picker) → 确认已进入选人界面
6. _select_contact_from_picker()      → SearchContactFinder / CompositeContactFinder 等策略
7. _confirm_send()                    → 精确匹配 Send，避免 “Send to:” 等误触
8. _record_share()（成功路径）        → 幂等表（若适用）
```

### 附件面板与「第二页」名片入口

WeCom 会将最近使用过的附件选项提升到第一页，因此 `_open_contact_card_menu()`：

1. **快速路径**：在当前附件网格页用 **精确文本**匹配 `CARD_TEXT_PATTERNS`（见下）并点击。
2. **慢速路径**：在附件菜单 **GridView** 上 **向左滑动**，翻到下一页后再匹配。

**人工操作要点（与自动化一致）**：在 `+` 弹出的网格上滑动时，**不要紧贴屏幕左右边缘滑动**，否则会触发系统返回/边缘手势，网格不会翻页。自动化侧通过 **加大边缘内缩与滑动时长** 缓解（见实现备忘）。

### 文本与 resourceId 的使用规则

| 用途 | 规则 |
|------|------|
| **Contact Card 菜单项** | 仅用 **精确文本**匹配 `CARD_TEXT_PATTERNS`（`Contact Card` / `名片` / `Personal Card` 等）。**不要**用附件项通用 label 的 `resourceId` 作为唯一键——同一 build 下多项共享同一 label id（legacy `aha`，新 build `aif`）。 |
| **附件面板是否打开** | 可用 GridView（`ahe` 或 `aij`）或 **≥4** 个附件 label 节点（`aha` 或 `aif`）作为 `PageStateValidator` 信号。 |
| **发送按钮** | 精确匹配 `Send` / `发送` 等，避免匹配到 “Send to:” 等标签。 |

### 自适应页查找与联系人选择

- **SearchContactFinder**（推荐）：点击搜索 → 输入姓名 → 选结果（联系人多时更稳）。
- **ScrollContactFinder**：仅在确认 **联系人选择器已打开** 后滚动列表；否则拒绝扫描，避免误点附件面板等区域。
- **CompositeContactFinder**：组合策略，按配置回退。

搜索流程要点：

1. 点击右上角区域 **搜索** 按钮（历史上常用 `ndb`；**不要**点最角落的关闭类按钮如 `nd7`）。
2. 在出现的 **EditText** 中输入名称，在结果区匹配（排除输入框自身）。

### 真机 Resource ID 映射（参考，非穷举）

| 步骤 | ResId（示例） | 说明 |
|------|---------------|------|
| 附件按钮 | `i9u`, `id8`, **`igu`** | 多版本；未命中时用右下角位置启发式 |
| 附件菜单 GridView | **`ahe`**（旧）, **`aij`**（720×1612 某 build） | 左滑翻页的目标容器 |
| 附件项 label（仅状态识别） | **`aha`**（旧）, **`aif`**（新） | 每项一行文案；**不能**单独用于点「名片」 |
| 名片菜单项 | （共用 label id） | **必须用 `CARD_TEXT_PATTERNS` 精确文本** |
| 选择器标题 / 列表 | `nca`, `cth` 等 | 见 `selectors.py` |
| 确认发送 | `dak` / `blz` / `i_2` 等 + 精确文本 | 见 `selectors.py` |

## 架构

```
客户发送图片/视频
    ↓
MessageProcessor._maybe_emit_media_event()
    ↓
[review-gate 开启] → pending_reviews → … → ReviewGate
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
  │     ├── _assert_page_state(attach_panel)
  │     ├── _open_contact_card_menu()  ← 内含 _tap_contact_card_menu / _swipe_attach_grid
  │     ├── _assert_page_state(contact_picker)
  │     ├── _select_contact_from_picker(contact_name)
  │     ├── _confirm_send()
  │     └── _record_share()  ← 成功时写入幂等表
  └── finally: restore_navigation()  ← 尽量恢复私聊列表
```

### 可观测性与诊断

- **指标**：`contact_share_attempt`、`contact_share_ui_dump` 等（见 `metrics_logger` 调用处）。
- **UI dump**：状态断言失败或 Contact Card 菜单阶段彻底失败时，可能写入  
  `logs/contact_share_dump_<timestamp>_<step>.json`（含完整 `elements` + `ui_tree`）。
- **桌面端**：媒体动作页可配置 `contact_name`，并提供「测试可达性」等能力（见后端 `media_actions` 路由与 `MediaActionsView.vue`）。

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
| `contact_name` | string | 全局默认主管名（须能在企业通讯录中搜到；详见页面提示与测试接口） |
| `skip_if_already_shared` | boolean | 幂等：已推过则跳过 |
| `cooldown_seconds` | int | 冷却时间（预留） |
| `kefu_overrides` | object | 按客服配置不同主管，key 为 kefu_name |

更细的 UI 字段（如发送前话术、失败兜底话术）以 `ContactShareRequest` / 设置加载为准。

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

若曾因「假成功」写入错误行，可使用仓库内一次性清理脚本（见 `scripts/cleanup_fake_contact_share_2026_05_06.py`，使用前阅读脚本说明）。

## 文件清单

### 核心模块

| 文件 | 说明 |
|------|------|
| `src/wecom_automation/services/contact_share/__init__.py` | 模块导出 |
| `src/wecom_automation/services/contact_share/models.py` | `ContactShareRequest`, `ContactShareResult` |
| `src/wecom_automation/services/contact_share/selectors.py` | UI 模式（附件 / 网格 / 文案） |
| `src/wecom_automation/services/contact_share/page_state.py` | `PageStateValidator` |
| `src/wecom_automation/services/contact_share/service.py` | `ContactShareService` |
| `src/wecom_automation/services/ui_search/` | 联系人查找策略与工具 |
| `src/wecom_automation/services/media_actions/actions/auto_contact_share.py` | `AutoContactShareAction` |

### 测试（单元）

| 路径 | 说明 |
|------|------|
| `tests/unit/test_auto_contact_share_action.py` | Action 与总线集成 |
| `tests/unit/test_contact_share_service.py` | 分享服务（预发话术、状态断言、滑动几何、诊断等） |
| `tests/unit/test_page_state_validator.py` | 页面状态识别 |
| `tests/unit/test_contact_finder_strategy.py` | 查找策略与 Composite / 滚动守卫 |
| `tests/unit/test_ui_search_helpers.py` | `find_elements_by_keywords` 匹配模式等 |

可选真机：`tests/integration/test_contact_search_e2e.py`（需设备）。

## 注意事项

- `contact_name` 必须在企业通讯录中可搜索；仅出现在客户列表里的备注名可能无法分享。
- 附件网格翻页：**避免边缘滑动**；自动化使用加大边缘内缩与滑动时长（见 [实现备忘](../implementation/2026-05-07-contact-share-reliability.md)）。
- 名片菜单项必须用 **精确文本**匹配；禁止依赖共享 `resourceId` 作为唯一选择器。
- 联系人选择器中搜索按钮与关闭按钮不要混淆（避免误关选择器）。
- `restore_navigation()` 在 `finally` 中尽力执行，保证失败后仍尝试回到可扫描列表状态。
- 重大 selector 变更后：跑单元测试 + 真机冒烟；失败时优先查看 **`logs/contact_share_dump_*.json`**。
