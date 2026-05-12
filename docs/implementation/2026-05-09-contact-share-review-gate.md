# Auto Contact Share Review Gate — Integration & E2E (2026-05-09)

> **日期**: 2026-05-09（修订：同日复核 db_path 与真机正向路径）  
> **关联**: [Auto Contact Share](../features/auto-contact-share.md) | [Media Auto-Actions](../features/media-auto-actions.md)

## 背景

`AutoContactShareAction` 之前没有检查图片审核结果：客户发图/视频后无论审核是否通过都可能推送名片。产品需要 **先走 image-rating-server，审核通过（人像 + `decision == 合格`）后再发名片**，并具备可观测日志。

## 行为摘要（review_gate）

- `review_gate.enabled = true`：`should_execute()` 通过 `evaluate_gate_pass()` 读 **设备会话库** `images` / `videos` 上的 `ai_review_*`；`gate_pass` 为真才继续。
- `review_gate.enabled = false`：不查审核，保持旧行为（仅受 `auto_contact_share.enabled` 等约束）。
- `has_data = false`：记 WARNING 并跳过（避免 fail-open）。

## 代码改动（按模块）

### 1. `AutoContactShareAction`

**文件**: `src/wecom_automation/services/media_actions/actions/auto_contact_share.py`

- `should_execute()` 调用 `evaluate_gate_pass()`（与 `auto_group_invite` / 可选门控的 `auto_blacklist` 共用 `media_review_decision`）。

### 2. 双库语义：`build_media_event_bus`

**文件**: `src/wecom_automation/services/media_actions/factory.py`

实时回复与桌面控制库分离时：

| 参数 | 用途 |
|------|------|
| `db_path` | **设备会话库**（`messages` / `images` / `videos`）。`AutoContactShareAction.db_path`、`AutoGroupInviteAction.db_path`、`AutoBlacklistAction` 的 gate 查询均指向此文件。 |
| `effects_db_path` | **控制库**：`BlacklistWriter`、`GroupChatService`、**`ContactShareService`（`media_action_contact_shares` 幂等表）**。 |

**历史错误（已修）**：曾把 `effects_db_path`（控制库）误传给 `AutoContactShareAction.db_path`，导致 `evaluate_gate_pass` 在控制库查不到 `images` 行 → `image_row_missing` / 门控永远失败；`upload_image_for_review` 若默认落到控制库也会出现「审核日志显示完成但门控读不到」的割裂。

### 3. 消息处理器：审核结果写回会话库

**文件**:

- `src/wecom_automation/services/message/handlers/image.py` — `_trigger_image_review` 将 `ConversationRepository.db_path` 或 `followup` 版 `_db_path` 传给 `upload_image_for_review(..., db_path=...)`。
- `src/wecom_automation/services/message/handlers/video.py` — 视频审核同样传入设备会话库路径。

这样 `_persist_review_to_local_db` 更新的 `images` / `videos` 行与 `evaluate_gate_pass` 读取的库一致。

### 4. Review gate runtime（占位 + 注入）

**文件**: `wecom-desktop/backend/services/review_gate_runtime.py`

- Webhook / 占位注册的 `AutoContactShareAction` 仍可能 `db_path=None`；真机路径以 `response_detector` → `build_media_event_bus` 为准。

**2026-05-12 更正（SSOT）**：图片审核服务器的 **HTTP 基址与超时** 不再存放在 `media_auto_actions.review_gate`（已移除 `rating_server_url` / `upload_timeout_seconds` / `upload_max_attempts`）。与实时回复路径一致，统一在 **`general.image_server_ip`**、**`general.image_review_timeout_seconds`**、**`general.image_upload_enabled`**（系统设置「图片审核」页）配置；`review_gate` 仅保留门控开关与 `video_review_policy`。详见 [Media actions settings dedup (SSOT)](./2026-05-12-media-actions-settings-dedup-ssot.md)。

## 端到端数据流（实时回复）

```
客户发图
  → ImageMessageHandler.process()
       → add_message_if_not_exists（会话库）
       → 保存图片 → upload_image_for_review(db_path=会话库)
       → 轮询 → 写入 images.ai_review_*
  → MessageProcessor._maybe_emit_media_event()
  → MediaEventBus.emit()
       → AutoContactShareAction.should_execute()
            → evaluate_gate_pass(db_path=会话库)
       → execute() → ContactShareService(db_path=控制库)  // 幂等 + UI
```

## 可观测性（日志关键词）

在设备日志 / `realtime_reply` 日志中可按序检索：

1. `image_review_client: uploading` — 上传至 **`general.image_server_ip`** 所配置的 rating-server 基址（如 `POST .../api/v1/upload`）；与 `build_review_components` 使用的地址同源（2026-05-12 起不再使用 `review_gate.rating_server_url`）。
2. `image_review_client: review completed ... decision=合格|不合格` — 审核结束。
3. `Auto-contact-share gate passed` 或 `Skipping auto-contact-share: review gate rejected` — 门控结果（含 `message_id`、`details`）。
4. `Starting auto-contact-share` / `Pre-share message sent` / `Shared contact card` — 名片链路。

**负向示例**：`decision=不合格` → `Skipping auto-contact-share: review gate rejected`（不应出现 `Shared contact card`）。

**正向示例**：`decision=合格` → `Auto-contact-share gate passed` → `Starting auto-contact-share` → `Shared contact card '…' to customer …`。

## 真机 E2E 记录（2026-05-09）

- **设备**: `10AE9P1DTT002LE`  
- **客户**: `B2604250558-(保底正常)`（测试前需非黑名单、且 `media_auto_actions` 总开关与 `auto_contact_share.enabled` 为真）。  
- **结果**: `score=8.0 decision=合格` → 前置话术发送 → `Shared contact card '孙德家'`；控制库 `media_action_contact_shares` 写入 `status=shared`。

联调注意：`auto_blacklist.enabled = true` 时，客户一发媒体就可能被拉黑，后续红点扫描直接 skip；测「过审后发名片」时可临时关闭自动拉黑或改用未拉黑账号（见 [Media Auto-Actions](../features/media-auto-actions.md)）。

## 已知限制：图片消息去重 hash 碰撞

`MessageRecord.compute_hash()` 对图片使用 bounds + 时间桶等字段。若 **不同日期** 发送的多张图在 UI 上 **bounds 相同** 且 **无可靠 `timestamp_raw`**，可能被误判为同一条消息 → `add_message_if_not_exists` 跳过 → **不会触发保存与审核** → 门控与名片都不会走。

**缓解（运维）**：排查时若见 `Stored: 0 | Skipped: N` 且会话里确有新图，可对比会话库是否已有同 bounds 的 `image` 行；必要时删除冲突旧行后重扫（仅测试环境）。

**后续（产品/代码）**：收紧图片 hash（例如纳入更细时间戳、序列号或文件指纹）的改动应带单元测试回归（见 `tests/unit` 中 `MessageRecord` / 处理器相关用例）。

## 测试

- `tests/unit/test_auto_contact_share_action.py`、`test_media_review_decision.py` — 门控与动作行为。
- `tests/unit/test_media_actions_factory.py` — 工厂：`effects_db_path` 与 **会话库 `db_path`** 分离时，门控动作用会话库、幂等/副作用用控制库（见 `test_conversation_db_for_gate_side_effects_db_for_services`）。

运行：`pytest tests/unit/test_media_actions_factory.py tests/unit/test_auto_contact_share_action.py tests/unit/test_media_review_decision.py -q`
