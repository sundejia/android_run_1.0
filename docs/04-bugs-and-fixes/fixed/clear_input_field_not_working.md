# Bug: 清空输入框功能失效

## 问题描述

- **现象**: 输入消息前，清空输入框的功能无法正常工作
- **影响**: 如果连接中断后恢复，输入框中的残留文本可能与新消息合并，导致发送错误内容

## 根因分析

在 `wecom_service.py` 的 `_clear_input_field()` 方法（第 2189-2222 行）中，代码调用了 **不存在的方法** `self.adb.run_command()`：

```python
# 原始错误代码
await self.adb.run_command("adb shell input keyevent KEYCODE_CTRL_LEFT KEYCODE_A")
await self.adb.run_command("adb shell input keyevent KEYCODE_DEL")
```

### 问题

1. `AdbService` 类中没有 `run_command` 方法
2. 调用不存在的方法会抛出 `AttributeError`
3. 异常被 `except` 捕获并静默处理（只打印 warning 日志）
4. 结果是**清空输入框的功能完全失效**

### 日志表现

如果查看日志，应该能看到：

```
WARNING - Failed to clear input field: 'AdbService' object has no attribute 'run_command'
```

## 修复方案

使用 `adb_service.py` 中已有的 `clear_text_field()` 方法：

```python
# 修复后的代码
async def _clear_input_field(self) -> None:
    try:
        self.logger.debug("Clearing input field...")

        # Use the adb_service's clear_text_field method which presses DEL key multiple times
        await self.adb.clear_text_field()

        self.logger.debug("Input field cleared")

    except Exception as e:
        self.logger.warning(f"Failed to clear input field: {e}")
```

### `clear_text_field()` 方法实现

该方法位于 `adb_service.py` 第 985-1000 行：

```python
async def clear_text_field(self) -> None:
    """Clear the currently focused text field using Select All + Delete."""
    self.logger.debug("Clearing text field")
    try:
        # Press delete multiple times to clear text
        for _ in range(50):  # Clear up to 50 characters
            await self.adb.press_key(67)  # KEYCODE_DEL
        self.invalidate_cache()
    except Exception as e:
        self.logger.error(f"Clear text field failed: {e}")
        raise WeComAutomationError(...)
```

## 修复状态

- ✅ 已修复
- 修复时间: 2026-01-19
- 修复文件: `src/wecom_automation/services/wecom_service.py`

## 经验教训

1. **代码审查**：调用外部方法前应验证方法是否存在
2. **异常处理**：静默捕获异常会隐藏严重问题，应考虑在开发环境打印更详细的错误信息
3. **单元测试**：应该为关键功能编写单元测试，确保接口兼容性
