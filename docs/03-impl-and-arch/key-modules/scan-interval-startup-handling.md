# 启动时传递的「扫描间隔」是否会被处理

## 结论

**会处理。** 启动实时回复时传递的「扫描间隔」（`scan_interval`）会从 API 一路传到子进程，并在主循环中用于控制两次扫描之间的等待时间。

## 处理流程

### 1. API 层：接收参数

- **位置**：`wecom-desktop/backend/routers/realtime_reply.py` → `start_device`
- **参数**：`scan_interval: int = Query(60, ge=10, le=600)`
  - 默认 60 秒
  - 取值范围：10～600 秒（含）
- **传递**：调用 `manager.start_realtime_reply(serial, scan_interval=scan_interval, ...)`

```python
@router.post("/device/{serial}/start")
async def start_device(
    serial: str,
    scan_interval: int = Query(60, ge=10, le=600),
    use_ai_reply: bool = Query(True),
    send_via_sidecar: bool = Query(True),
):
    ...
    success = await manager.start_realtime_reply(
        serial=serial,
        scan_interval=scan_interval,
        ...
    )
```

### 2. Manager 层：拼进子进程命令行

- **位置**：`wecom-desktop/backend/services/realtime_reply_manager.py` → `start_realtime_reply`
- **行为**：把 `scan_interval` 作为 `--scan-interval` 传给子进程

```python
cmd = [
    "uv", "run",
    str(script_path),   # realtime_reply_process.py
    "--serial", serial,
    "--scan-interval", str(scan_interval),
]
# ...
process = await self._create_subprocess(cmd, env)
```

### 3. 子进程：解析并使用

- **位置**：`wecom-desktop/backend/scripts/realtime_reply_process.py`
- **解析**：`parse_args()` 中定义 `--scan-interval`，存入 `args.scan_interval`（默认 60）

```python
parser.add_argument(
    "--scan-interval",
    type=int,
    default=60,
    help="Scan interval in seconds (default: 60)"
)
# 解析后: args.scan_interval
```

- **使用**：在 `run(args)` 的主循环中：
  1. 启动时打日志：`Scan Interval: {args.scan_interval}s`
  2. 每次扫描周期结束后：`await asyncio.sleep(args.scan_interval)`，再进入下一轮扫描
  3. 若本周期因 skip 标志被跳过，同样先 `await asyncio.sleep(args.scan_interval)` 再继续

```python
# 主循环
while True:
    ...
    if check_skip_flag(args.serial):
        ...
        await asyncio.sleep(args.scan_interval)
        continue
    result = await detector.detect_and_reply(...)
    ...
    await asyncio.sleep(args.scan_interval)   # 等待下一个扫描周期
```

因此，**启动时传的扫描间隔会完整参与子进程逻辑**：解析 → 日志 → 两次扫描之间的 sleep，均使用该值。

## 小结

| 环节         | 文件/位置                                            | 对 scan_interval 的处理                          |
| ------------ | ---------------------------------------------------- | ------------------------------------------------ |
| 启动 API     | `realtime_reply.py` → `start_device`                 | Query 参数，ge=10, le=600，默认 60               |
| 进程管理     | `realtime_reply_manager.py` → `start_realtime_reply` | 拼进命令行 `--scan-interval`                     |
| 子进程入口   | `realtime_reply_process.py` → `parse_args`           | 解析为 `args.scan_interval`                      |
| 子进程主循环 | `realtime_reply_process.py` → `run(args)`            | `asyncio.sleep(args.scan_interval)` 控制扫描间隔 |

**结论**：启动时传递的「扫描间隔」会被完整处理，并实际用于控制实时回复的扫描周期。
