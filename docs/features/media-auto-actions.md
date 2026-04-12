# Media Auto-Actions（客户发图/视频后的自动动作）

> **状态**: 已实现  
> **最后更新**: 2026-04-12（多机型：`ui_parser` 启发式 + 选择器扩展；`WeComService` 滚动区按真机分辨率缩放、拉群步骤内用 UI 树根 bounds 刷新宽高并以**比例阈值**匹配无文案控件；关键步骤 **3 次重试**；DroidRun 多设备端口；实时自动拉群后 **恢复私聊列表**；详见 [多机型可靠性](../implementation/2026-04-12-auto-group-invite-multi-device-reliability.md)、[多分辨率与端口](../bugs/2026-04-12-multi-resolution-group-invite-and-droidrun-port-fix.md)、[私聊导航](../bugs/2026-04-12-auto-group-invite-private-chats-navigation.md)）

## 功能概述

当**客户**（非客服）在会话中发送**图片或视频**并成功写入会话库后，系统可按配置自动执行：

1. **自动拉黑**：将客户写入控制库 `blacklist` 表（与现有黑名单页、同步过滤逻辑一致）。
2. **自动拉群**：在安卓端通过 `GroupInviteWorkflowService` + `WeComService` 执行完整拉群与可选的建群后首条消息发送；消息内容与群名均支持模板变量（见下文「拉群实现状态」与 [实现说明](../implementation/2026-04-05-media-auto-actions-custom-message-and-chat-header-menu.md)）。

配置在桌面端 **Media Auto-Actions** 页面（路由 `/media-actions`，侧栏 📸），设置持久化在控制库 `settings` 表中，类别键为 `media_auto_actions`。

## 架构

- **事件模型**：`MediaEvent`（`src/wecom_automation/services/media_actions/interfaces.py`）描述一次「客户媒体已落库」事件。
- **事件总线**：`MediaEventBus`（`event_bus.py`）按注册顺序调用多个 `IMediaAction`；单动作异常不阻塞后续动作。
- **动作**：
  - `AutoBlacklistAction` → `BlacklistWriter.add_to_blacklist`（`actions/auto_blacklist.py`）
  - `AutoGroupInviteAction` → `GroupChatService`（`actions/auto_group_invite.py` + `group_chat_service.py`）
- **独立拉群工作流**：`src/wecom_automation/services/group_invite/` 定义可复用的 `GroupInviteRequest` / `GroupInviteWorkflowService`，由 `GroupChatService` 作为兼容层委托执行，供手动触发和媒体自动触发共用。
- **同步集成**：`create_sync_orchestrator` / `create_customer_syncer`（`services/sync/factory.py`）在创建 `MessageProcessor` 时，若 DB 中 `media_auto_actions.enabled` 为真，则挂载总线与上述动作，并从同一 DB 加载子配置（`settings_loader.py`）。
- **消息入口**：`MessageProcessor.process` 在责任链处理完成后，若结果为 `image`/`video` 且消息来自客户，则 `emit` 事件（`services/message/processor.py`）。

## 设置结构（`settings` 表）

类别：`media_auto_actions`。键：

| 键                  | 类型    | 说明                                                                                                                                                                                                    |
| ------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`           | boolean | 总开关                                                                                                                                                                                                  |
| `auto_blacklist`    | json    | `enabled`, `reason`, `skip_if_already_blacklisted`                                                                                                                                                      |
| `auto_group_invite` | json    | `enabled`, `group_members`, `group_name_template`, `skip_if_group_exists`, `member_source`, `send_test_message_after_create`, `test_message_text`, `post_confirm_wait_seconds`, `duplicate_name_policy` |

默认值与类型在 `wecom-desktop/backend/services/settings/defaults.py` 的 `SETTING_DEFINITIONS` 中注册，确保 JSON 子配置正确序列化。

## HTTP API

前缀：`/api/media-actions`（`wecom-desktop/backend/routers/media_actions.py`）

- `GET /settings` — 读取合并后的配置
- `PUT /settings` — 部分更新并广播 `media_action_settings_updated`（全局 WebSocket）
- `GET /logs` — 预留/查询动作日志表（若表不存在则返回空列表）
- `POST /test-trigger` — 手动构造 `MediaEvent` 并走**独立**的 `MediaEventBus`（见 `routers/media_actions.py`）。**自动拉黑**在开启时可能真实写库。**自动拉群**在该入口使用无 `WeComService` 的 `GroupChatService()`，**不会在真机上执行 UI 拉群**；日志中可能出现 `No WeComService available; recording group creation intent only`。验证真机拉群与消息内容请走同步/实时消息链路或带 `WeComService` 的集成路径，勿仅依赖此接口。

## 前端

- 页面：`wecom-desktop/src/views/MediaActionsView.vue`
- API：`api.getMediaActionSettings` / `updateMediaActionSettings` / `testTriggerMediaAction`（`services/api.ts`）
- 全局 WS 事件类型扩展：`media_action_triggered`、`blacklist_updated`、`media_action_settings_updated`（`stores/globalWebSocket.ts`）

### 国际化（i18n）

页面已完成中英双语支持，所有 UI 字符串通过 `useI18n` composable 的 `t()` 函数渲染：

- 翻译键类别：`media_actions`（含建群后消息、预览等扩展键；定义在 `wecom-desktop/backend/i18n/translations.py`）
- 侧栏导航：`nav.media_actions`（en: "Media Auto-Actions"，zh-CN: "媒体自动操作"）
- 覆盖范围：页面标题、描述、表单标签、占位符、按钮文本、Toast 消息、测试区域标签、入群消息模板与预览提示

## 拉群实现状态

`GroupChatService` 现在会把请求转交给 `GroupInviteWorkflowService`，后者复用 `WeComService` 的安卓 UI 能力完成以下流程：

1. 进入客户聊天窗口
2. 打开右上角聊天信息页
3. 点击客户头像旁 `+`
4. 点击搜索按钮并逐个搜索、勾选成员
5. 默认在多个同名结果中选择第一个
6. 点击确认/创建群聊
7. 等待约 1 秒并确认自动进入群聊聊天页
8. 在输入框发送建群后消息（默认 `测试`；可在设置中改为模板，占位符与群名模板一致：`{customer_name}`、`{kefu_name}`、`{device_serial}`）。模板在 `AutoGroupInviteAction` 中解析为最终字符串后再传入工作流。

当前群名重命名仍为 best-effort 钩子，不影响主流程成功与否；后续可继续在 `wecom_service.py` 中增强不同企业微信版本下的控件识别与群名编辑能力，而无需改动动作接口。

**聊天页右上角菜单**：部分企业微信版本将「更多」渲染为无文案的可点击 `TextView` / `RelativeLayout`。`open_chat_info` 使用的 `_find_group_invite_menu_button` 已扩展树形递归与头部区域启发式（见 [实现说明](../implementation/2026-04-05-media-auto-actions-custom-message-and-chat-header-menu.md)）。

### 多版本 / 多分辨率可靠性（2026-04-12）

- **客户媒体识别**：`MessageProcessor` 依赖的 `UIParser` 对图片 / 视频等尽量使用 **bounds + className + 文案正则**，减少对易变 `resourceId` 的依赖；否则不同 WeCom 小版本会导致根本不触发 `MediaEvent`。
- **拉群 UI**：`WeComService` 在打开聊天信息、添加成员、搜索选人、确认建群等步骤带 **重试与日志**；首次导航前通过 `_ensure_screen_resolution()` 将 **滚动/滑动** 相关配置按真机分辨率相对 **1080×2340** 缩放；每个 UI dump 后通过 `_update_screen_dimensions()` 用树根 bounds 刷新宽高，**无文案「加号」等回退匹配使用屏幕比例阈值**（与 720p / 1080p 真机验证一致）；`group_invite/selectors.py` 持续扩展文案与 pattern。
- **诊断**：`scripts/diagnose_group_invite.py` 对在线设备采集版本、分辨率与 UI 样本；默认写入 `diagnostic_reports/`（仓库 `.gitignore` 忽略除 `README.md` 外的生成文件，见该目录说明）。
- **真机冒烟**（需 USB 调试与 DroidRun/Portal 可用）：  
  - `python scripts/run_group_invite_quick.py --all` — 列表首条客户，打开资料页 → 加号入口 → 返回，不建群。  
  - `python scripts/run_group_invite_full.py --serial <SERIAL> --member <姓名>` — 完整建群（会真实建群，仅用于受控环境）。  
  - `python scripts/run_group_invite_e2e.py --customer <列表完整显示名> [--member …] [--dry-run]` — 按指定客户名逐步验证（`navigate_to_chat` 需与列表 **完全一致** 的 `text`）。

### Windows / 实时跟进联调要点

- **依赖**：在仓库根目录执行 `uv sync --extra dev`；后端在 `wecom-desktop/backend` 用 `uv run uvicorn main:app --reload --port 8765`。不要用已删除的 `backend/requirements.txt`（见 `wecom-desktop/README.md`）。
- **实时会话**：`POST /api/realtime/device/{serial}/start` 启动设备实时跟进；日志中应出现 `Media auto-actions enabled`（来自 `response_detector` 挂载的 `MediaEventBus`）。
- **黑名单**：HTTP 前缀为 **`/api/blacklist/...`**。若客户在黑名单中，自动跟进会跳过该会话；联调时可 `POST /api/blacklist/remove`（或桌面黑名单页）放行后再测拉群。
- **DroidRun Portal**：若曾用 `uiautomator dump` 等占用无障碍，Portal 可能报无障碍不可用；按 `docs/04-bugs-and-fixes/fixed/BUG-2025-12-13-droidrun-portal-connection-failure.md` 重新启用 Portal 无障碍服务。
- **DroidRun 端口（多设备）**：实时跟进路径已修复端口传递链（`realtime_reply_manager` → `realtime_reply_process` → `response_detector`），每台设备通过 `PortAllocator` 分配独立端口，停止时释放。详见 [多分辨率拉群与端口修复](../bugs/2026-04-12-multi-resolution-group-invite-and-droidrun-port-fix.md)。
- **拉群后消息列表（私聊 vs 全部）**：工作流结束后 UI 在新**群聊**中；若在实时红点流程内触发自动拉群，必须在返回扫列表前回到 **「私聊」** 筛选，否则 `_detect_first_page_unread` 会在「全部」上扫红点。实现上由 `AutoGroupInviteAction` 的 `finally` 调用 `GroupChatService.restore_navigation()` → `WeComService.ensure_on_private_chats()`，且 `ensure_on_private_chats` 在从会话 `go_back()` 后会再次校验并必要时 `switch_to_private_chats()`；`response_detector` 在处理完单用户后 Step 7 再次调用 `ensure_on_private_chats()` 兜底。详见 [Bug 记录](../bugs/2026-04-12-auto-group-invite-private-chats-navigation.md)。
- **拉群成功判定**：`GroupInviteWorkflowService` 在确认建群后依赖 `WeComService.confirm_group_creation` → `get_current_screen() == "chat"`。外部群/中文标题（如 `群聊(N)`）与仅含 `ListView` 的消息区已纳入 `_is_chat_screen` 启发式；详见 [实现说明：黑名单 shim 与联调](../implementation/2026-04-05-blacklist-shim-sync-media-bus-runbook.md)。

## 黑名单扩展

`BlacklistWriter.is_blacklisted_by_name(device_serial, customer_name)` 用于自动拉黑前的去重判断（`blacklist_service.py`）。

## 测试

| 范围                   | 路径                                                                                                      |
| ---------------------- | --------------------------------------------------------------------------------------------------------- |
| 事件总线与动作         | `tests/unit/test_media_event_bus.py`, `test_auto_blacklist_action.py`, `test_auto_group_invite_action.py` |
| Processor + 总线集成   | `tests/unit/test_media_action_integration.py`                                                             |
| 设置加载               | `tests/unit/test_media_actions_settings_loader.py`                                                        |
| 拉群工作流/兼容层      | `tests/unit/test_group_invite_workflow.py`, `tests/unit/test_group_chat_service.py`                       |
| 同步工厂 + 媒体总线    | `tests/unit/test_sync_factory.py`                                                                         |
| 会话屏检测（拉群确认） | `tests/unit/test_wecom_service_screen_detection.py`                                                       |
| FastAPI                | `wecom-desktop/backend/tests/test_media_actions_api.py`                                                   |
| 前端 API 客户端        | `wecom-desktop/src/views/mediaActions.spec.ts`                                                            |
| 前端页面（组件）       | `wecom-desktop/src/views/MediaActionsView.spec.ts`                                                        |
| 聊天信息菜单启发式     | `tests/unit/test_wecom_service_opt.py`（`TestGroupInviteMenuDetection`）                                  |
| 多机型拉群与解析（回归） | 上述用例 + `test_ui_parser.py`、`test_wecom_service_screen_detection.py` 等；重大改动后建议再跑 `run_group_invite_quick.py --all` |
| 完整真机拉群流程       | `tests/integration/test_group_invite_e2e.py`（10 步 E2E，720p + 1080p 验证通过；需在线设备）              |

运行后端单测目录时注意 pytest `testpaths`：需使用  
`pytest wecom-desktop/backend/tests/test_media_actions_api.py --override-ini="testpaths=."`  
或进入 backend 目录按项目文档执行。

## 相关文档

- [安卓拉群工作流实现说明](../implementation/2026-04-04-android-group-invite-workflow.md) — 模块划分、时序、配置与限制（含建群后 `restore_navigation`）
- [自动拉群后私聊列表导航](../bugs/2026-04-12-auto-group-invite-private-chats-navigation.md) — 实时跟进场景根因与三层修复
- [自定义建群后消息与聊天页菜单兼容](../implementation/2026-04-05-media-auto-actions-custom-message-and-chat-header-menu.md) — 模板、API/UI 对齐、`test-trigger` 语义、真机验证说明
- [黑名单 shim、同步媒体总线与 Windows 联调](../implementation/2026-04-05-blacklist-shim-sync-media-bus-runbook.md)
- [多机型 / 多分辨率自动拉群可靠性](../implementation/2026-04-12-auto-group-invite-multi-device-reliability.md) — 诊断脚本、解析与 UI 改动摘要、真机验证说明
- [黑名单系统](../01-product/blacklist-system.md) — 数据模型与 `BlacklistWriter` / `BlacklistChecker`
- [测试目录约定](../07-appendix/test-organization.md)
