# BOSS 直聘 M0–M6 端到端测试报告

- **测试日期**: 2026-05-08
- **测试设备**: vivo V2357A (serial `10AE9P1DTT002LE`), Android
- **BOSS App**: `com.hpbr.bosszhipin` (已登录，VIP 账号 2027-03-10 到期)
- **账号身份**: 马先生 / 慧莱娱乐 / 人事主管 / 5 个在线职位
- **代码分支**: `fix/boss-e2e-pr2-parser-schema-may2026`

## 执行摘要

| 里程碑 | 功能 | 当前结果 | 说明 |
|---|---|---|---|
| M1 | Recruiter Bootstrap | 通过 | recruiter row 已可通过 API 绑定设备 |
| M2 | Job Sync | 部分通过 | production ADB factory 已接线；job-list parser 仍需单独跟进真机页 drift |
| M3 | Greet Executor | 通过 | 真机 `test-run` 成功打开牛人名片并点击 `立即沟通` |
| M4 | Reply Dispatcher | 通过（dry-run） | 真机消息页识别未读并生成回复；默认不发送 |
| M5 | Re-engagement | 代码完成，需复测 | 依赖 M4 dispatcher；真实发送仍需显式确认 |
| M6 | Monitoring / Ops | 通过 | summary API 和 resilience metrics 可用 |

**当前判断**: May-2026 BOSS app 的两条用户可见主链路已恢复：

1. 牛人页 → 解析候选人 → 打开名片 → 识别详情页 → 点击 `立即沟通`。
2. 消息页 → 解析未读会话 → 打开会话/简历 → 生成回复文本；默认 dry-run，不触发输入或发送。

---

## 本次修复内容

### 1. May-2026 BOSS UI parser 兼容

- `candidate_card_parser.py`
  - 支持真实牛人页 `rv_list`、`tv_geek_name`、`tv_work_edu_other_desc`、`tv_content`。
  - 支持 DroidRun native `get_state()` 输出的扁平 clickable text tree。
  - 无真实 ID badge 时生成稳定 `live:<sha1>` fallback candidate ID。
  - 从候选人节点 bounds 生成 tap target，供 executor 坐标点击。
- `message_list_parser.py`
  - 支持真实消息页 `recyclerView`、`tv_name`、`tv_position`、`tv_msg`。
  - 支持扁平 clickable text tree。
  - unread detection fail-closed：仅在左侧头像区域附近明确出现数字 badge 时返回 `unread_count > 0`。
- `greet_state_detector.py`
  - 支持详情页只暴露纯文本 `立即沟通`、没有 `btn_chat_now` resourceId 的情况。

### 2. DroidRun runtime 兼容

- `DroidRunAdapter.get_state()` 现在能把 DroidRun native 返回的 `**Current Phone State:** ... Current Clickable UI elements ...` 文本格式解析成简化 UI tree。
- portal fallback 仍保留；native text-state path 用于避免 parser 只能处理 dict tree 时误判为空。
- 新增 `AdbPort.tap(x, y)`，production adapter 通过 `adb shell input tap` 实现。

### 3. Greet open reliability

- `GreetExecutor` 优先使用 parser 提供的候选人 tap target 坐标打开名片。
- 坐标点击失败时回退到 `tap_by_text(candidate.name)`。
- 保留原有发送前 guard：时间窗口、quota、黑名单 pick-time / pre-send 二次检查、risk-control/unknown-UI halt。

### 4. Reply send-safety

- `/api/boss/messages/dispatch` 请求体新增：
  - `dry_run: bool = true`
  - `confirm_send: bool = false`
- 默认行为是 dry-run：解析、打开、生成文本后返回 `dry_run_ready`，不会 `type_text()`，不会点击 `发送`。
- 真实发送必须同时传 `"dry_run": false` 和 `"confirm_send": true`。

### 5. Desktop startup fixes

- `wecom-desktop/package.json` backend script 改为 `python -m uvicorn ... --app-dir backend`，避免 `.venv/bin/uvicorn` stale shebang。
- Electron main/preload/scrcpy manager 改为 default import `electron` 后 destructuring，避免 CommonJS named export runtime error。

---

## 真机验证记录

### Greet test-run

前提：设备停在 BOSS 牛人 feed。

```bash
curl -sS -X POST http://127.0.0.1:8765/api/boss/greet/test-run \
  -H 'Content-Type: application/json' \
  -d '{"device_serial":"10AE9P1DTT002LE"}'
```

结果：

```json
{"outcome":"sent","boss_candidate_id":"live:372f8a0e7fa9914f","candidate_name":"邓铭月","detail":null}
```

说明：这条 probe 实际点击了 `立即沟通`。不要在未授权外发的环境中运行该 probe。

### Message dispatch dry-run

前提：设备停在 BOSS 消息页。

```bash
curl -sS -X POST http://127.0.0.1:8765/api/boss/messages/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"device_serial":"10AE9P1DTT002LE","dry_run":true}'
```

结果：

```json
{
  "outcome":"dry_run_ready",
  "boss_candidate_id":"live:136af1f07923824f",
  "candidate_name":"刘女士",
  "text_sent":"您好 刘女士，看到您的简历，请问方便沟通吗？",
  "template_warnings":[]
}
```

说明：dry-run 未输入文本，未点击 `发送`。

---

## Regression fixtures

新增/更新的真机 fixture：

- `tests/fixtures/boss/runtime_probe/retry_20260508_185850.{json,png}` — May-2026 牛人 feed。
- `tests/fixtures/boss/runtime_probe/post_restart_20260508.{json,png}` — backend restart 后消息页状态。
- `tests/fixtures/boss/messages_list/e2e_20260508_retry.{json,png}` — May-2026 消息列表。
- `tests/fixtures/boss/candidate_detail/after_greet_open_20260508.{json,png}` — 真实候选人详情页，`立即沟通` 为纯文本节点。

这些 fixture 必须和对应 parser/service 测试一起提交，避免后续 BOSS app UI drift 静默破坏主链路。

---

## Verification

已运行：

```bash
python -m pytest -p no:logfire \
  tests/unit/boss/parsers/test_greet_state_detector.py \
  tests/unit/boss/parsers/test_candidate_card_parser.py \
  tests/unit/boss/parsers/test_message_list_parser.py \
  tests/unit/boss/services/test_greet_executor.py \
  tests/unit/boss/services/test_reply_dispatcher.py -q
# 40 passed

python -m ruff check \
  src/boss_automation/parsers/candidate_card_parser.py \
  src/boss_automation/parsers/message_list_parser.py \
  src/boss_automation/parsers/greet_state_detector.py \
  src/boss_automation/services/adb_port.py \
  src/boss_automation/services/droidrun_adapter.py \
  src/boss_automation/services/greet/greet_executor.py \
  src/boss_automation/services/reply_dispatcher.py \
  wecom-desktop/backend/routers/boss_messages.py
# All checks passed

npm --prefix wecom-desktop run typecheck
npm --prefix wecom-desktop run build
```

`pytest` uses `-p no:logfire` because the local environment has a stale transitive Logfire/OpenTelemetry plugin import (`ReadableLogRecord`). The BOSS tests themselves are current and were not skipped.

---

## Remaining follow-ups

1. Job sync should get the same May-2026 live fixture refresh treatment as candidate/message pages.
2. Recruiter profile auto-detection remains a follow-up if operator-supplied recruiter snapshots are not acceptable.
3. Real reply send should only be tested with explicit authorization and `dry_run=false, confirm_send=true`.
4. If DroidRun changes its native text-state format, keep `_tree_from_clickable_state_text()` covered by a unit fixture before updating production parsing.
