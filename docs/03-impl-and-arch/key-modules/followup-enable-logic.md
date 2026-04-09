# 补刀启用逻辑（当前实现）

本文说明当前代码里“补刀（followup）什么时候会生效、什么时候不会生效”。

## 1. 开关来源与默认值

- 配置项是 `followup.followup_enabled`（后端内部键名）。
- 默认值是 `false`（默认不启用）。
- 前端页面使用 `followupEnabled`，通过 `GET/POST /api/followup/settings` 读写该配置。
- 配置持久化在统一设置服务（`settings` 分类体系）中。

## 2. 触发时机（重点）

补刀不是独立定时器，不会因为“开关打开”就单独跑起来。  
当前触发条件是：

1. 设备的实时回复进程在运行（`realtime_reply_process.py` 循环中）。
2. 一轮实时扫描处理完红点用户后，队列清空（没有待处理红点）。
3. 或者首次扫描就直接没有红点用户（空闲态）。
4. 满足上述任一情况时，`ResponseDetector` 会调用 `_try_followup_if_idle(...)` 进入一次补刀检查。

也就是说：

- 只开 `followup_enabled=true`，但实时回复进程没运行 -> 补刀不会执行。
- 实时回复在忙红点用户 -> 先处理红点，补刀延后。

## 3. 启用判定（真正“是否执行”）

在补刀检查阶段，`FollowupQueueManager` 会做两层判定：

1. `is_enabled()`
   - 直接读取 `settings.followup_enabled`。
   - `false` 则直接返回“补刀未启用”。

2. `can_execute()`
   - 先看 `followup_enabled`。
   - 再看工作时间限制：
     - `enable_operating_hours=false` -> 不限制时间，允许执行。
     - `enable_operating_hours=true` -> 当前时间必须在 `start_hour ~ end_hour` 才允许执行。

只有以上都通过，才会进入“构建队列 + 执行补刀”阶段。

## 4. 补刀候选与执行门槛

即使“启用判定通过”，还要有可执行任务才会真正发补刀：

1. 从数据库构建近期会话列表。
2. 按规则更新补刀队列（空闲阈值、最大尝试次数等）。
3. 查询待补刀数量 `pending_count`：
   - `0` -> 结束，不发送任何补刀。
   - `>0` -> 执行 `execute_pending_followups(...)`。

执行时还会受这些设置约束：

- `max_followups`：每轮最多执行多少个。
- `attempt_intervals`：第 N 次补刀前要满足的间隔。
- `use_ai_reply`：是否走 AI 生成补刀文案（否则走模板文案）。
- 黑名单命中用户会被跳过。

## 5. 一句话总结

当前“补刀启用逻辑”是：

**`followup_enabled=true` 只是“允许补刀”的前置条件；实际执行还依赖实时回复进程正在跑、当前无红点待处理、工作时间校验通过、且队列里存在满足条件的待补刀对象。**

## 6. 关键代码位置

- 配置默认值：`wecom-desktop/backend/services/settings/defaults.py`
- 配置模型：`wecom-desktop/backend/services/settings/models.py`
- 补刀设置读写：`wecom-desktop/backend/routers/followup_manage.py`
- 实时流程触发补刀：`wecom-desktop/backend/services/followup/response_detector.py`
- 启用与可执行判定：`wecom-desktop/backend/services/followup/queue_manager.py`
- 实时进程主循环：`wecom-desktop/backend/scripts/realtime_reply_process.py`
