# Swipe 日志刷屏问题分析与修复

## 问题描述

日志中大量出现以下重复信息，刷屏严重，阻挡其他日志显示：

```
22:40:55    [INFO]    sync: Swiped from (540, 400) to (540, 1000) in 300 milliseconds
22:40:55    [INFO]    sync: Swiped from (540, 400) to (540, 1000) in 300 milliseconds
22:40:55    [INFO]    sync: Swiped from (540, 400) to (540, 1000) in 300 milliseconds
... (连续重复 8 次)
```

**特点**：

- 同一时间戳 (22:40:55) 连续出现多条
- 每隔一段时间出现一堆
- 参数固定：`(540, 400) -> (540, 1000), 300ms`

## 根本原因

### 1. 日志来源

这条日志来自**底层第三方库 droidrun (AdbTools)**，不是我们项目代码输出的。

调用链：

```
scroll_to_top() / scroll_up()
    ↓
ADBService.swipe()
    ↓
AdbTools.swipe()  ← droidrun 库在这里输出日志
```

### 2. 为什么是这个坐标？

从配置分析 (`core/config.py`)：

- `scroll_up_start_y = 400`
- `scroll_up_end_y = 1000`
- `start_x = 540` (屏幕中心)
- `swipe_duration_ms = 300`

坐标 `(540, 400) -> (540, 1000)` 对应的是 **scroll_up** 操作（向上滚动，显示上方内容）。

### 3. 为什么集中在同一时间出现？

这些日志来自 `scroll_to_top()` 方法的循环调用：

```python
async def scroll_to_top(self, scroll_count: int = 1000):
    for attempt in range(1, max_attempts + 1):
        await self.scroll_up()      # 每次都触发底层日志
        await asyncio.sleep(0.3)    # 短暂等待
        # 检测 UI 是否稳定...
```

**循环特性**：

- 默认 `scroll_count=1000`（最大尝试次数）
- 每次循环间隔约 0.3 秒
- 直到 UI 连续 3 次不变化才停止
- 如果列表很长，可能需要滚动 50-200 次

因此，在短时间内会产生大量连续的 swipe 日志。

### 4. 现有聚合机制的局限

虽然 `adb_service.py` 已经实现了 swipe 统计聚合功能：

- `_count_swipe()` 统计不同类型的 swipe
- `log_swipe_statistics()` 输出聚合统计

**但问题是**：底层 droidrun 库自己的日志并没有被抑制，每次调用 `AdbTools.swipe()` 仍然会输出日志。

## 解决方案

### 方案 1: 抑制 droidrun 库的日志

在应用启动时，将 droidrun 相关 logger 的级别设置为 WARNING：

```python
import logging

# 在应用初始化时添加
logging.getLogger("droidrun").setLevel(logging.WARNING)
logging.getLogger("droidrun.tools").setLevel(logging.WARNING)
logging.getLogger("droidrun.tools.adb").setLevel(logging.WARNING)
```

**优点**：

- 简单有效
- 不修改 droidrun 库代码

**缺点**：

- 会过滤掉所有 INFO 级别日志，包括可能有用的其他信息

### 方案 2: 动态调整日志级别

在执行批量操作前临时抑制，操作后恢复：

```python
async def scroll_to_top(self, scroll_count: int = 1000):
    # 临时抑制 droidrun 日志
    droidrun_logger = logging.getLogger("droidrun")
    original_level = droidrun_logger.level
    droidrun_logger.setLevel(logging.WARNING)

    try:
        # 执行滚动操作...
        for attempt in range(1, max_attempts + 1):
            await self.scroll_up()
            # ...
    finally:
        # 恢复原始日志级别
        droidrun_logger.setLevel(original_level)
```

### 方案 3: 使用自定义 Filter 过滤 ✅ **已实施**

添加一个过滤器来精确过滤特定模式的日志：

```python
class SwipeLogFilter(logging.Filter):
    """
    Filter to suppress verbose "Swiped from ... to ... in ... milliseconds" logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        # Filter out "Swiped from (x, y) to (x, y) in N milliseconds" logs
        if "Swiped from" in message and "milliseconds" in message:
            return False
        return True

# 应用过滤器
swipe_filter = SwipeLogFilter()
for logger_name in ["droidrun", "droidrun.tools", "droidrun.tools.adb"]:
    logging.getLogger(logger_name).addFilter(swipe_filter)
```

**优点**：

- 精确过滤，只过滤 "Swiped from" 日志
- 保留 droidrun 库的其他有用日志
- 不影响日志级别

## 实施详情

### 修改的文件

**`src/wecom_automation/core/logging.py`**

1. 添加了 `SwipeLogFilter` 类：
   - 继承自 `logging.Filter`
   - 检查日志消息是否包含 "Swiped from" 和 "milliseconds"
   - 匹配的日志返回 `False`（不显示），其他返回 `True`（正常显示）

2. 在 `setup_logger()` 函数中应用过滤器：
   - 创建 `SwipeLogFilter` 实例
   - 将过滤器添加到 droidrun 相关的所有 logger

### 效果

| 日志类型                                                    | 修复前                    | 修复后    |
| ----------------------------------------------------------- | ------------------------- | --------- |
| `Swiped from (540, 400) to (540, 1000) in 300 milliseconds` | ✅ 显示（每次滑动都出现） | ❌ 不显示 |
| droidrun 其他 INFO 日志                                     | ✅ 显示                   | ✅ 显示   |
| droidrun WARNING/ERROR 日志                                 | ✅ 显示                   | ✅ 显示   |
| 项目自己的 `[Swipe Stats]` 聚合日志                         | ✅ 显示                   | ✅ 显示   |

## 相关文件

- `src/wecom_automation/core/logging.py` - 日志配置和过滤器实现
- `src/wecom_automation/services/adb_service.py` - ADB 服务和 swipe 统计
- `src/wecom_automation/core/config.py` - 滚动参数配置
- `docs/swipe-log-analysis.md` - 详细 swipe 日志分析文档
