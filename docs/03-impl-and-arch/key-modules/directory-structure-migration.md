# 日志目录结构迁移指南

## 迁移概述

从旧的 stdlib logging 多目录结构迁移到 loguru 的扁平化目录结构。

## 目录结构对比

### ❌ 旧结构（已废弃）

```
logs/
├── backend/
│   ├── backend.log
│   └── backend.log.YYYY-MM-DD (轮转文件)
├── followup/
│   ├── scanner.log
│   ├── response_detector.log
│   ├── message_tracker.log
│   ├── followup.log
│   └── *.log.YYYY-MM-DD (轮转文件)
└── metrics/
    ├── metrics.jsonl
    └── metrics.jsonl.YYYY-MM-DD (轮转文件)
```

**问题：**

- 多设备日志混写同一文件
- 子目录过多，难以管理
- 50+ 个轮转文件分散在不同目录

### ✅ 新结构（Loguru）

```
logs/
├── {hostname}-global.log                    # 后端全局日志
├── {hostname}-global.YYYY-MM-DD.log         # 自动轮转
├── {hostname}-{serial}.log                  # 设备专属日志
├── {hostname}-{serial}.YYYY-MM-DD.log       # 自动轮转
└── metrics/
    ├── {hostname}-{serial}.jsonl            # 设备专属指标
    └── {hostname}-{serial}.YYYY-MM-DD.jsonl # 自动轮转
```

**优势：**

- ✅ 每设备独立文件，完全隔离
- ✅ 扁平化结构，易于查找
- ✅ 自动轮转和清理（保留 30 天）
- ✅ 文件名包含主机名，支持分布式部署

## 迁移步骤

### 1. 清理旧目录

```bash
# 删除旧的日志子目录
rm -rf logs/backend/
rm -rf logs/followup/

# 保留 logs/ 和 logs/metrics/ 根目录
```

### 2. 更新 `ensure_directories()`

**文件：** `wecom-desktop/backend/main.py`

```python
# ❌ 旧代码
directories = [
    project_root / "logs" / "backend",    # 删除
]

# ✅ 新代码
directories = [
    project_root / "logs",                 # 全局日志目录
    project_root / "logs" / "metrics",     # 指标日志目录
]
```

### 3. 标记遗留代码

**文件：** `wecom-desktop/backend/services/followup/service.py`

```python
"""
Follow-up Service - 精简版（LEGACY）

⚠️ DEPRECATED: This service is legacy code.
   New architecture uses realtime_reply_process.py and RealtimeReplyManager.
"""
```

## 配置验证

### 启动时检查

运行后端启动时，应该看到：

```
[startup] [OK] Ensured directory exists: logs
[startup] [OK] Ensured directory exists: logs/metrics
[startup] Initializing logging for hostname: your-hostname
[startup] Logging configured: logs/your-hostname-global.log
```

### 日志文件验证

运行一个设备同步后，检查日志文件：

```bash
ls -lh logs/
# 应该看到：
# your-hostname-global.log
# your-hostname-DEVICE_SERIAL.log

ls -lh logs/metrics/
# 应该看到：
# your-hostname-DEVICE_SERIAL.jsonl
```

## 遗留代码处理

### FollowUpService (Legacy)

**状态：** 已弃用，但保留以防万一

**修改：**

- 日志路径：`logs/followup/followup.log` → `logs/followup-service-legacy.log`
- 保留时间：永久 → 7 天
- 添加 DEPRECATED 警告

**推荐：** 如果确认不再使用，可以完全删除此类。

### 检查遗留引用

```bash
# 搜索旧目录引用
grep -r "logs/backend" --include="*.py"
grep -r "logs/followup" --include="*.py"

# 应该没有活动引用（除了 service.py 中的遗留代码）
```

## 故障排除

### 目录不存在错误

**症状：**

```
FileNotFoundError: [Errno 2] No such file or directory: 'logs/backend'
```

**解决：**

1. 检查 `ensure_directories()` 是否已更新
2. 确认启动日志显示正确的目录创建
3. 手动创建 `logs/` 目录：`mkdir -p logs/metrics`

### 旧日志文件残留

**症状：** 旧的 `logs/backend/` 或 `logs/followup/` 目录仍然存在

**解决：**

```bash
# 备份旧日志（如果需要）
tar -czf logs-backup-$(date +%Y%m%d).tar.gz logs/backend logs/followup

# 删除旧目录
rm -rf logs/backend logs/followup
```

### 权限问题

**症状：** 无法创建日志目录或文件

**解决：**

```bash
# 检查权限
ls -ld logs/

# 修复权限
chmod 755 logs/
chmod 755 logs/metrics/
```

## 相关文件

- `wecom-desktop/backend/main.py` - 目录创建逻辑
- `src/wecom_automation/core/logging.py` - Loguru 配置
- `wecom-desktop/backend/services/followup/service.py` - 遗留代码
- `docs/03-impl-and-arch/key-modules/logging-system-architecture.md` - 日志系统架构

## 迁移检查清单

- [x] 清理旧日志目录（`logs/backend/`, `logs/followup/`）
- [x] 更新 `ensure_directories()` 移除旧路径
- [x] 标记遗留代码（`FollowUpService`）
- [x] 验证新日志文件正确创建
- [x] 验证语法（`py_compile`）
- [x] 更新文档

## 迁移完成时间

**迁移日期：** 2026-02-06  
**涉及文件：** 2 个  
**删除的目录：** 2 个（`logs/backend/`, `logs/followup/`）  
**新建的目录：** 1 个（`logs/metrics/` - 如果不存在）
