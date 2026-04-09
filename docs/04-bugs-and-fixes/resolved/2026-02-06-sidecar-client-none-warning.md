# Sidecar Client None Warning 修复

**日期：** 2026-02-06  
**严重程度：** Medium  
**状态：** ✅ 已修复  
**影响范围：** 实时回复进程 Sidecar 集成

## 问题描述

### 症状

在实时回复进程运行时出现警告：

```
[WARNING] [FOLLOWUP] [AN2FVB1706003302] ⚠️ Skip check skipped: sidecar client is None
```

即使命令行参数传递了 `--send-via-sidecar`，sidecar client 仍然是 None。

### 影响

- ⚠️ 无法使用 Sidecar 发送消息（退化为直接发送）
- ⚠️ 无法检测操作员跳过请求
- ⚠️ 无法清理过期消息

## 根本原因

### 设计冲突

存在两个不同的 Sidecar Client 创建路径：

**路径 1：命令行参数（realtime_reply_process.py）**

```python
# realtime_reply_process.py 第 188-194 行
sidecar_client = None
if args.send_via_sidecar:  # ← 命令行参数
    try:
        sidecar_client = SidecarQueueClient(args.serial)
        logger.info("Sidecar client initialized")
    except Exception as e:
        logger.warning(f"Failed to init Sidecar client: {e}")
```

**路径 2：数据库设置（response_detector.py）**

```python
# response_detector.py 第 550-559 行
sidecar_client = None
try:
    service = get_followup_service()
    sidecar_client = service.get_sidecar_client(serial)  # ← 从数据库读取
    # service.get_sidecar_client() 内部检查 realtime_settings.send_via_sidecar
    if not send_via_sidecar:  # 如果数据库设置是 False，返回 None
        return None
```

### 问题所在

1. `realtime_reply_process.py` 根据命令行参数创建了 `sidecar_client`
2. 但是调用 `detect_and_reply()` 时**没有传递**这个 client
3. `detect_and_reply()` 内部重新获取，但使用数据库设置（可能是 False）
4. 导致即使命令行传了参数，内部还是获取到 None

### 优先级混乱

命令行参数应该有更高优先级，但当前实现中：

- 数据库设置 > 命令行参数 ❌

正确应该是：

- 命令行参数 > 数据库设置 ✅

## 修复方案

### 修改 1: ResponseDetector.detect_and_reply() 添加参数

**文件：** `wecom-desktop/backend/services/followup/response_detector.py`

```python
async def detect_and_reply(
    self,
    device_serial: str | None = None,
    interactive_wait_timeout: int = 40,
    sidecar_client: Any | None = None,  # ← 新增参数
) -> dict[str, Any]:
    """
    Args:
        sidecar_client: Sidecar 客户端（可选，如果传入则优先使用，否则从设置获取）
    """
```

### 修改 2: 优先使用传入的 client

**文件：** `wecom-desktop/backend/services/followup/response_detector.py`

```python
# Initialize Sidecar Client (if not provided and enabled in settings)
# Priority: use provided sidecar_client > fallback to service.get_sidecar_client()
if sidecar_client is None:  # ← 只在未提供时才从设置获取
    try:
        from .service import get_followup_service
        service = get_followup_service()
        sidecar_client = service.get_sidecar_client(serial)
        if sidecar_client:
            self._logger.info(f"[{serial}] ✅ Sidecar client created from settings")
        else:
            self._logger.info(f"[{serial}] ⚠️ Sidecar disabled in settings or failed to initialize")
    except Exception as e:
        self._logger.error(f"[{serial}] Failed to init sidecar client: {e}")
else:
    self._logger.info(f"[{serial}] ✅ Using provided sidecar client (from command line)")  # ← 新增日志
```

### 修改 3: 传递 client 参数

**文件：** `wecom-desktop/backend/scripts/realtime_reply_process.py`

```python
# 调用检测器（传递 sidecar_client）
result = await detector.detect_and_reply(
    device_serial=args.serial,
    interactive_wait_timeout=10,
    sidecar_client=sidecar_client,  # ← 传递命令行创建的 client
)
```

## 验证

### 语法验证

```bash
✅ python -m py_compile response_detector.py
✅ python -m py_compile realtime_reply_process.py
```

### 预期行为

**场景 1：命令行传递 `--send-via-sidecar`**

```
[INFO] Sidecar client initialized
[INFO] ✅ Using provided sidecar client (from command line)
[INFO] 🚀 Sidecar enabled for this scan
```

**场景 2：数据库设置启用 Sidecar**

```
[INFO] ✅ Sidecar client created from settings
[INFO] 🚀 Sidecar enabled for this scan
```

**场景 3：两者都禁用**

```
[INFO] ⚠️ Sidecar disabled in settings or failed to initialize
[INFO] Will use direct send instead
```

## 优先级规则（修复后）

```
命令行参数 --send-via-sidecar
    ↓ 如果提供
    ✅ 使用命令行创建的 client（优先）
    ↓ 如果未提供
    检查数据库 realtime_settings.send_via_sidecar
        ↓ 如果启用
        ✅ 从设置创建 client
        ↓ 如果禁用
        ❌ client = None（使用直接发送）
```

## 相关代码

- `wecom-desktop/backend/services/followup/response_detector.py` - 第 408-412 行（方法签名）
- `wecom-desktop/backend/services/followup/response_detector.py` - 第 549-566 行（client 初始化）
- `wecom-desktop/backend/scripts/realtime_reply_process.py` - 第 188-218 行（调用点）
- `wecom-desktop/backend/services/followup/service.py` - 第 242-272 行（get_sidecar_client 方法）

## 经验教训

### 1. 参数优先级设计

当一个功能可以通过多种方式配置时，明确优先级顺序：

```
命令行参数 > 环境变量 > 数据库设置 > 默认值
```

### 2. 依赖注入 vs 内部创建

**方案 A（推荐）：依赖注入**

```python
def process(client: Client):  # ← 外部传入
    client.do_something()
```

**方案 B（避免）：内部创建**

```python
def process():
    client = create_client_from_settings()  # ← 内部创建，难以覆盖
    client.do_something()
```

### 3. 参数传递完整性

创建的对象应该传递到所有需要它的地方：

```python
# ❌ 错误：创建了但没传递
client = create_client(args)
detector.process()  # 内部重新创建，忽略外部 client

# ✅ 正确：显式传递
client = create_client(args)
detector.process(client=client)  # 使用外部 client
```

## 测试建议

### 测试用例 1：命令行参数优先级

```bash
# 数据库设置 send_via_sidecar=False
# 命令行传递 --send-via-sidecar

python realtime_reply_process.py --serial TEST --send-via-sidecar

# 预期：使用 Sidecar（命令行优先）
# 日志：✅ Using provided sidecar client (from command line)
```

### 测试用例 2：数据库设置生效

```bash
# 数据库设置 send_via_sidecar=True
# 命令行不传递 --send-via-sidecar

python realtime_reply_process.py --serial TEST

# 预期：使用 Sidecar（从数据库加载）
# 日志：✅ Sidecar client created from settings
```

### 测试用例 3：都禁用

```bash
# 数据库设置 send_via_sidecar=False
# 命令行不传递 --send-via-sidecar

python realtime_reply_process.py --serial TEST

# 预期：直接发送（不使用 Sidecar）
# 日志：⚠️ Sidecar disabled in settings or failed to initialize
```

## 相关问题

- `docs/bugs/2026-02-05-sidecar-queue-message-sent-to-wrong-person.md` - Sidecar 队列系统设计
- `docs/03-impl-and-arch/experiments/MESSAGE_SENDING_FLOW.md` - 消息发送流程

## 修复时间

**修复日期：** 2026-02-06  
**修复文件：** 2 个  
**代码行数：** ~20 行
