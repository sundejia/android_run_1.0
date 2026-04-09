# Followup Queue Manager Log Callback 参数错误

**日期**: 2026-02-03  
**状态**: ✅ 已修复  
**错误类型**: TypeError

## 错误信息

```
[WARNING]
[FOLLOWUP]
[1558183796001U9] Followup error: get_followup_queue_manager() got an unexpected keyword argument 'log_callback'
```

## 根本原因分析

### 问题描述

工厂函数 `get_followup_queue_manager()` 的签名与调用方不匹配：

- **函数定义**（`queue_manager.py` 第 580-592 行）：只接受 3 个参数

  ```python
  def get_followup_queue_manager(
      device_serial: str,
      adb: Optional[AdbTools] = None,
      db_path: Optional[str] = None,
  ) -> FollowupQueueManager:
  ```

- **调用位置**（`response_detector.py` 第 2081-2086 行）：传递了 4 个参数
  ```python
  queue_manager = get_followup_queue_manager(
      device_serial=serial,
      adb=wecom.adb,
      db_path=self._repository._db_path,
      log_callback=lambda msg, level: self._logger.info(f"[{serial}] [Followup] {msg}"),
  )
  ```

### 代码不一致性

`FollowupQueueManager` 类本身是支持 `log_callback` 参数的（第 59-65 行）：

```python
def __init__(
    self,
    device_serial: str,
    adb: Optional[AdbTools] = None,
    db_path: Optional[str] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,  # ← 支持
):
```

但工厂函数遗漏了这个参数。

## 修复方案

在 `queue_manager.py` 的 `get_followup_queue_manager()` 函数中添加 `log_callback` 参数：

```python
def get_followup_queue_manager(
    device_serial: str,
    adb: Optional[AdbTools] = None,
    db_path: Optional[str] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,  # 新增
) -> FollowupQueueManager:
    """获取指定设备的补刀队列管理器"""
    if device_serial not in _queue_managers:
        _queue_managers[device_serial] = FollowupQueueManager(
            device_serial=device_serial,
            adb=adb,
            db_path=db_path,
            log_callback=log_callback,  # 新增
        )
    return _queue_managers[device_serial]
```

## 修改的文件

| 文件                                                               | 修改内容                                                         |
| ------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/queue_manager.py` | 在 `get_followup_queue_manager()` 函数中添加 `log_callback` 参数 |

---

# 相关问题：前端 Followup 数据页面字段不匹配

**日期**: 2026-02-03  
**状态**: ✅ 已修复  
**错误类型**: SQL 字段名不匹配

## 问题描述

前端 Followup 数据管理页面无法正确显示数据库中的补刀记录，因为后端 API 使用的字段名与实际表结构完全不匹配。

### 根本原因

`followup_manage.py` 中的 API 使用了错误的表结构和字段名：

| API 使用的字段              | 实际表结构字段         | 说明                                   |
| --------------------------- | ---------------------- | -------------------------------------- |
| `customer_id` (INTEGER, FK) | `customer_name` (TEXT) | 实际直接存储客户名称                   |
| `attempt_number`            | `current_attempt`      | 字段名不同                             |
| `message_preview`           | 不存在                 | 实际表无此字段                         |
| `responded`                 | 不存在                 | 使用 status='completed' 替代           |
| `response_time_seconds`     | 不存在                 | 需要计算 updated_at - last_followup_at |
| `LEFT JOIN customers`       | 不需要                 | customer_name 直接存储                 |

### 修复内容

1. **`_ensure_followup_tables`**: 使用正确的表结构（与 `attempts_repository.py` 一致）
2. **`get_attempts`**: 添加 `device_serial` 参数，使用正确的字段名查询
3. **`get_analytics`**: 使用 `current_attempt` 和 `status='completed'` 替代旧字段
4. **`export_data`**: 添加 `device_serial` 参数，使用正确的字段名导出

## 完整修改的文件

| 文件                                               | 修改内容                                   |
| -------------------------------------------------- | ------------------------------------------ |
| `wecom-desktop/backend/routers/followup_manage.py` | 修复所有 API 的 SQL 查询，使用正确的字段名 |

## 影响范围

- 补刀（Followup）系统的初始化流程
- 实时回复扫描后的空闲补刀检测功能
- 前端补刀数据管理页面的数据展示
- 数据导出功能

## 验证方法

1. 运行实时回复扫描功能
2. 等待扫描完成进入空闲状态
3. 确认不再出现 `got an unexpected keyword argument 'log_callback'` 错误
4. 确认补刀日志正常输出
