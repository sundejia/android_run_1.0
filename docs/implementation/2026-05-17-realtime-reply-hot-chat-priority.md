# 实时回复：热聊优先红点队列

**日期**: 2026-05-17
**类型**: Enhancement
**范围**: `wecom-desktop/backend/services/followup/response_detector.py`

## 动机

原始实现使用单个 `deque` 处理红点用户。每次处理完一个用户后重新检测红点，新发现的用户统一 `appendleft` 到队首。拼接顺序 `new_users + reprocess_users` 导致新陌生人被排在已聊过的用户前面。

产品需求："如果你和这个人已经聊了，就保持热聊。" 即已经对话过的用户再次回复时，应优先于从未对话过的新陌生人被点击。

## 方案

将单 `deque` 拆分为两层队列：

| 队列 | 含义 | 优先级 |
|------|------|--------|
| `hot_queue` | 本轮 scan 已聊过、又冒红点的用户 | 高（始终先处理） |
| `cold_queue` | 首次出现在本轮 scan 的红点用户 | 低 |

主循环逻辑：`hot_queue` 不空时从 hot 取；空了才从 cold 取。

每次处理完一个用户后重新检测红点：
- 用户名在 `processed_names` 中 → 进 `hot_queue`（已聊过又回来了）
- 用户名既不在 `processed_names` 也不在 `queued_names` → 进 `cold_queue`（新陌生人）

## 变更文件

| 文件 | 变更 |
|------|------|
| `wecom-desktop/backend/services/followup/response_detector.py` | `_scan_device_for_responses` 内队列逻辑重构 |
| `wecom-desktop/backend/tests/test_response_detector_hot_priority.py` | 新增 4 个单测 |
| `docs/03-impl-and-arch/key-modules/followup-phase2-implementation.md` | §3.2 更新伪代码和流程图 |

## 行为不变项

- `_detect_first_page_unread`（dayblock / 低置信度过滤 / screen guard）不动
- `_process_unread_user_with_wait`（黑名单 / cooldown / 交互等待）不动
- `processed_names` / `queued_names` / `skipped_names` 语义不变
- SkipRequested 时清空双队列

## 测试覆盖

1. `test_reprocess_wins_over_new_stranger_same_cycle` — 同一次再检测里 reprocess 先于 new
2. `test_existing_cold_does_not_jump_over_returning_hot` — cold 里已有陌生人时后到的 hot 仍优先
3. `test_no_regression_pure_fifo_when_no_replies` — 无 reprocess 时保持原始 FIFO
4. `test_multiple_hot_users_keep_detection_order` — 多个 hot 用户保持检测顺序
