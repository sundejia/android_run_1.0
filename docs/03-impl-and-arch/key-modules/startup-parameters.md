# Realtime Reply 启动参数文档

## 概述

Realtime Reply（实时回复）系统是为企业微信（WeCom）设计的 AI 驱动即时响应功能。它能够自动检测客户消息并生成回复，支持多设备独立运行。

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                   Frontend (Vue.js)                         │
│           RealtimeView.vue - 设备管理界面                   │
└────────────────────────┬────────────────────────────────────┘
                         │ REST API
┌────────────────────────▼────────────────────────────────────┐
│              FastAPI Backend (followup.py)                  │
│       ../03-impl-and-arch/key-modules/realtime/device/{serial}/start                 │
│         RealtimeReplyManager - 进程管理器                   │
└────────────────────────┬────────────────────────────────────┘
                         │ subprocess
┌────────────────────────▼────────────────────────────────────┐
│         realtime_reply_process.py (独立子进程)              │
│    ResponseDetector - 消息检测与AI回复生成                  │
└─────────────────────────────────────────────────────────────┘
```

## 启动参数

### 命令行参数

当通过命令行直接启动 `realtime_reply_process.py` 时，支持以下参数：

| 参数                 | 类型   | 必需 | 默认值 | 范围/限制 | 描述                                   |
| -------------------- | ------ | ---- | ------ | --------- | -------------------------------------- |
| `--serial`           | string | ✅   | -      | -         | 设备序列号（ADB 设备标识符）           |
| `--scan-interval`    | int    | ❌   | 60     | 10-600 秒 | 扫描新消息的间隔时间                   |
| `--use-ai-reply`     | flag   | ❌   | False  | -         | 启用 AI 生成回复（需要配置 AI 服务器） |
| `--send-via-sidecar` | flag   | ❌   | False  | -         | 通过 Sidecar 发送以供人工审核          |
| `--debug`            | flag   | ❌   | False  | -         | 启用调试日志（DEBUG 级别）             |

### API 启动参数

当通过 FastAPI API 启动时，参数通过 Query Parameters 传递：

**端点**: `POS../03-impl-and-arch/key-modules/realtime/device/{serial}/start`

| 参数               | 类型  | 必需 | 默认值 | 范围/限制 | 描述                       |
| ------------------ | ----- | ---- | ------ | --------- | -------------------------- |
| `serial`           | path  | ✅   | -      | -         | 设备序列号（URL 路径参数） |
| `scan_interval`    | query | ❌   | 60     | 10-600    | 扫描间隔（秒）             |
| `use_ai_reply`     | query | ❌   | True   | -         | 使用 AI 生成回复           |
| `send_via_sidecar` | query | ❌   | True   | -         | 通过 Sidecar 发送          |

## 参数详解

### 1. scan_interval（扫描间隔）

**作用**: 控制系统检查新消息的频率

- **类型**: 整数
- **单位**: 秒
- **默认值**: 60
- **有效范围**: 10-600 秒

**推荐值**:

- **快速响应** (30-60秒): 适用于需要快速响应的场景
- **标准模式** (60-120秒): 平衡响应速度和系统负载
- **低负载模式** (120-300秒): 减少设备交互频率

**注意事项**:

- 过小的间隔值会增加设备 CPU 使用和功耗
- 过大的间隔值可能导致回复延迟
- 建议根据业务需求调整

### 2. use_ai_reply（使用 AI 回复）

**作用**: 启用 AI 服务生成回复内容

- **类型**: 布尔标志
- **默认值**: True（API）/ False（命令行）

**工作原理**:

1. 检测到客户消息后，系统会收集对话上下文
2. 调用配置的 AI 服务器（默认：`http://localhost:8000`）
3. AI 生成回复内容
4. 如果 `send_via_sidecar=True`，回复发送到 Sidecar 供审核
5. 如果 `send_via_sidecar=False`，回复直接发送

**依赖配置**:

- AI 服务器 URL（在全局设置中配置）
- AI 回复超时时间（1-30 秒）

**降级策略**:

- AI 服务器不可用时，使用预设的 mock 消息
- 超时后自动降级到 mock 消息

### 3. send_via_sidecar（通过 Sidecar 发送）

**作用**: 启用人工审核机制

- **类型**: 布尔标志
- **默认值**: True

**工作流程**:

1. AI 生成的回复首先发送到 Sidecar 队列
2. 前端 SidecarView 显示待发送的消息
3. 操作员可以：
   - **编辑**: 修改 AI 生成的内容
   - **跳过**: 取消发送
   - **发送**: 确认发送（10秒倒计时）
4. 倒计时期间检测到用户输入会自动暂停

**优点**:

- 人工审核确保回复质量
- 可以修正 AI 的不当回复
- 支持实时编辑和调整

### 4. debug（调试模式）

**作用**: 启用详细日志输出

- **类型**: 布尔标志
- **默认值**: False

**日志级别**:

- **False**: INFO 级别（关键信息）
- **True**: DEBUG 级别（详细调试信息）

**日志位置**:

- 文件: `lo../03-impl-and-arch/scanner.log`（按天轮转）
- 控制台: 输出到 stdout（由父进程捕获并转发到前端 WebSocket）

## 使用示例

### 命令行启动

```bash
# 基本启动（最小配置）
python realtime_reply_process.py --serial DEVICE_ABC123

# 启用 AI 回复和 Sidecar 审核
python realtime_reply_process.py \
    --serial DEVICE_ABC123 \
    --scan-interval 60 \
    --use-ai-reply \
    --send-via-sidecar

# 启用调试模式
python realtime_reply_process.py \
    --serial DEVICE_ABC123 \
    --scan-interval 30 \
    --use-ai-reply \
    --send-via-sidecar \
    --debug

# 快速扫描模式（30秒间隔）
python realtime_reply_process.py \
    --serial DEVICE_ABC123 \
    --scan-interval 30 \
    --use-ai-reply
```

### API 启动

**使用 cURL**:

```bash
# 启动实时回复
curl -X POST "http://localhost:87../03-impl-and-arch/key-modules/realtime/DEVICE_ABC123/start?scan_interval=60&use_ai_reply=true&send_via_sidecar=true"

# 停止实时回复
curl -X POST "http://localhost:87../03-impl-and-arch/key-modules/realtime/DEVICE_ABC123/stop"

# 暂停实时回复
curl -X POST "http://localhost:87../03-impl-and-arch/key-modules/realtime/DEVICE_ABC123/pause"

# 恢复实时回复
curl -X POST "http://localhost:87../03-impl-and-arch/key-modules/realtime/DEVICE_ABC123/resume"

# 获取状态
curl "http://localhost:87../03-impl-and-arch/key-modules/realtime/DEVICE_ABC123/status"
```

**使用 JavaScript (前端)**:

```javascript
// 启动实时回复
const response = await fetch(
  'http://localhost:87../03-impl-and-arch/key-modules/realtime/DEVICE_ABC123/start?' +
    new URLSearchParams({
      scan_interval: 60,
      use_ai_reply: true,
      send_via_sidecar: true,
    }),
  { method: 'POST' }
)

const data = await response.json()
console.log(data)
// { success: true, message: "Follow-up started for device DEVICE_ABC123", ... }
```

## API 响应格式

### 启动成功响应

```json
{
  "success": true,
  "message": "Follow-up started for device DEVICE_ABC123",
  "serial": "DEVICE_ABC123",
  "status": "running"
}
```

### 设备状态响应

```json
{
  "serial": "DEVICE_ABC123",
  "status": "running",
  "message": "Follow-up running",
  "responses_detected": 15,
  "replies_sent": 12,
  "started_at": "2025-01-30T10:30:00",
  "last_scan_at": "2025-01-30T11:45:00",
  "errors": []
}
```

### 状态值说明

| 状态       | 描述                                               |
| ---------- | -------------------------------------------------- |
| `idle`     | 设备空闲，未启动实时回复                           |
| `starting` | 正在启动中                                         |
| `running`  | 正在运行，定期扫描消息                             |
| `paused`   | 已暂停（Windows: Job Object 挂起 / Unix: SIGSTOP） |
| `stopped`  | 已停止                                             |
| `error`    | 发生错误                                           |

## 多设备管理

Realtime Reply 支持为每个设备启动独立的子进程，互不干扰：

```bash
# 设备 1
python realtime_reply_process.py --serial DEVICE_ABC123 --scan-interval 60

# 设备 2
python realtime_reply_process.py --serial DEVICE_DEF456 --scan-interval 90

# 设备 3
python realtime_reply_process.py --serial DEVICE_GHI789 --scan-interval 120
```

**获取所有设备状态**:

```bash
curl "http://localhost:87../03-impl-and-arch/key-modules/realtime/devices/status"
```

**响应**:

```json
{
  "devices": {
    "DEVICE_ABC123": {
      "serial": "DEVICE_ABC123",
      "status": "running",
      "message": "Follow-up running",
      "responses_detected": 15,
      "replies_sent": 12,
      ...
    },
    "DEVICE_DEF456": {
      "serial": "DEVICE_DEF456",
      "status": "idle",
      "message": "Ready to start",
      ...
    }
  },
  "total": 2,
  "running": 1
}
```

## 进程管理

### Windows 平台

使用 **Job Objects** 管理子进程：

- 启动时创建 Job Object
- 暂停/恢复通过 Job Object 控制
- 停止时使用 `taskkill /F /T` 终止进程树

### Unix/Linux 平台

使用 **进程组** 和 **信号** 管理：

- 启动时创建新进程组（`start_new_session=True`）
- 暂停: `SIGSTOP`
- 恢复: `SIGCONT`
- 停止: `SIGTERM` → `SIGKILL`

## 日志和监控

### 日志位置

**子进程日志**:

- 路径: `lo../03-impl-and-arch/scanner.log`
- 轮转: 按天（每天午夜创建新文件）
- 保留: 永久保留（`backupCount=0`）
- 编码: UTF-8

**前端日志**:

- 通过 WebSocket 实时推送到前端 Logs 面板
- 按设备隔离，支持多设备同时查看

### 监控指标

Realtime Reply 自动追踪以下指标：

- `responses_detected`: 检测到的客户回复数
- `replies_sent`: 已发送的回复数
- `started_at`: 启动时间
- `last_scan_at`: 上次扫描时间
- `errors`: 错误列表（最多保留 50 条）

## 配置持久化

启动参数在子进程生命周期内有效。重启后需要重新传递参数。

**全局设置**（通过 Settings API）:

- AI 服务器 URL
- AI 回复超时
- 这些设置影响所有使用 AI 回报的设备

**设备特定设置**:

- `scan_interval`: 每个设备独立配置
- `use_ai_reply`: 每个设备独立配置
- `send_via_sidecar`: 每个设备独立配置

## 故障排查

### 问题：进程无法启动

**检查**:

1. 设备是否通过 ADB 连接: `adb devices`
2. 设备序列号是否正确
3. 是否已有进程在运行（检查状态 API）

### 问题：AI 回复未生成

**检查**:

1. AI 服务器是否运行: `curl http://localhost:8000/health`
2. AI 服务器 URL 配置是否正确
3. 网络连接是否正常
4. 查看日志中的错误信息

### 问题：Sidecar 消息未显示

**检查**:

1. `send_via_sidecar` 是否为 `true`
2. Sidecar WebSocket 是否连接
3. 前端是否在 Sidecar 页面

## 相关文档

- [Realtime Reply 架构设计](./architecture.md)
- [Sidecar 集成指南](../03-impl-and-arch/integration.md)
- [AI 回复服务配置](../ai-reply/configuration.md)
- [多设备管理最佳实践](../devices/management.md)

## 版本历史

| 版本  | 日期       | 变更说明                   |
| ----- | ---------- | -------------------------- |
| 1.0.0 | 2025-01-30 | 初始版本，支持基本启动参数 |
