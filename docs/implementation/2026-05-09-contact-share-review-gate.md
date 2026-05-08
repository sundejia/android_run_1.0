# Auto Contact Share Review Gate Integration

> **日期**: 2026-05-09
> **关联**: [Auto Contact Share](../features/auto-contact-share.md) | [Media Auto-Actions](../features/media-auto-actions.md)

## 背景

`AutoContactShareAction` 之前没有检查图片审核结果：当客户发送图片/视频时，无论审核是否通过，名片都会直接发送。用户需要"图片先审核，审核通过后再发名片"的流程。

## 改动

### 1. `AutoContactShareAction` 新增审核门检查

**文件**: `src/wecom_automation/services/media_actions/actions/auto_contact_share.py`

在 `should_execute()` 中新增 `evaluate_gate_pass()` 调用，与 `auto_blacklist` / `auto_group_invite` 共享同一份 `media_review_decision` 判决逻辑。

- `review_gate.enabled = true` 时：读取 DB 中的审核结果（`is_portrait` + `decision`），只有审核通过才继续执行
- `review_gate.enabled = false` 时：跳过审核检查，直接执行（旧行为不变）
- 审核数据缺失（`has_data=False`）时跳过执行并记 WARNING

### 2. 构造函数新增 `db_path` 参数

`AutoContactShareAction.__init__()` 新增 `db_path: str | None = None` 参数，用于 `evaluate_gate_pass()` 查询审核结果。

### 3. 工厂层传递 `db_path`

**文件**: `src/wecom_automation/services/media_actions/factory.py`

`build_media_event_bus()` 注册 `AutoContactShareAction` 时传入 `db_path=effects_db_path`。

### 4. Review gate runtime 同步更新

**文件**: `wecom-desktop/backend/services/review_gate_runtime.py`

- `_register_default_actions()` 注册 `AutoContactShareAction` 时传入 `db_path=None`（占位）
- `bind_wecom_service()` 注入时同步设置 `action._db_path = db_path`

## 数据流

```
客户发送图片/视频
  → ImageMessageHandler (wait_for_review=True)
    → upload_image_for_review() → 上传到 image-rating-server
    → 轮询等待审核完成 → 结果写入 DB (images.ai_review_*)
  → MessageProcessor._maybe_emit_media_event()
    → MediaEventBus.emit()
      → AutoContactShareAction.should_execute()
        → evaluate_gate_pass(message_id, message_type, db_path, gate_enabled)
          → 读取 DB 中的 ai_review_status, ai_review_decision, ai_review_details_json
          → 判定: is_portrait AND decision=="合格" → gate_pass=True
        → gate_pass=True → 执行发名片
        → gate_pass=False → 跳过
```

## 测试

- 现有 39 个单元测试全部通过（`test_auto_contact_share_action.py` + `test_media_actions_factory.py`）
- `test_media_review_decision.py` 17 个审核门判定测试全部通过
