# Logging System Architecture Proposal

**Status**: Proposed
**Author**: Claude (Architect)
**Date**: 2026-02-09
**Related Issues**: Global log file locking on Windows

## Executive Summary

This proposal outlines a comprehensive logging architecture for the WeCom automation framework that addresses current issues while laying the foundation for future observability needs.

### Current State Analysis

**Strengths:**

- ✅ Unified loguru-based logging in Python framework
- ✅ Multi-device log isolation with device-specific sinks
- ✅ Structured metrics logging (JSON Lines format)
- ✅ Real-time log streaming via WebSocket
- ✅ Multi-process safe with `enqueue=True`

**Critical Issues:**

- ❌ Global log file causes Windows lock contention during parallel sync
- ⚠️ Mixed logging frameworks (loguru vs stdlib) causing compatibility issues
- ⚠️ No structured error tracking or aggregation
- ⚠️ Limited observability (no metrics/alerting beyond business events)
- ⚠️ Manual log cleanup and archival process

## Architecture Proposal

### Design Principles

1. **Zero Lock Contention**: Eliminate shared log files across processes
2. **Unified Framework**: Standardize on loguru across entire codebase
3. **Structured Logging**: All logs in JSON format for machine parsing
4. **Observable**: Built-in metrics, tracing, and alerting hooks
5. **Scalable**: Support for 10+ devices logging simultaneously

### Phase 1: Critical Fixes (Week 1)

#### 1.1 Remove Global Log File

**Problem**: All device processes write to `{hostname}-global.log`, causing Windows file lock contention.

**Solution**: Eliminate global log sink. Route logs as follows:

```
Before:
├── {hostname}-global.log        ❌ Shared by all processes
├── {hostname}-{serial1}.log     ✅ Device-specific
└── {hostname}-{serial2}.log     ✅ Device-specific

After:
├── {hostname}-system.log        ✅ Backend/main process only
├── {hostname}-{serial1}.log     ✅ Device subprocess
└── {hostname}-{serial2}.log     ✅ Device subprocess
```

**Implementation**:

```python
# logging.py - Modified init_logging()
def init_logging(
    hostname: str | None = None,
    level: str = "INFO",
    log_dir: Path | None = None,
    console: bool = True,
    process_type: Literal["main", "device", "subprocess"] = "main",
) -> None:
    """Initialize logging with process-type-specific sinks."""

    # ... existing setup ...

    # Process-specific routing
    if process_type == "main":
        # Main process: system logs only
        _loguru_logger.add(
            _log_dir / f"{hostname}-system.log",
            format=SAFE_LOG_FORMAT,
            rotation="00:00",
            retention="30 days",
            filter=lambda r: r["extra"].get("device") is None,
        )
    elif process_type == "device":
        # Device process: device-specific sink only
        serial = os.environ.get("WECOM_DEVICE_SERIAL", "unknown")
        _loguru_logger.add(
            _log_dir / f"{hostname}-{serial}.log",
            format=SAFE_LOG_FORMAT,
            rotation="00:00",
            retention="30 days",
        )

    # No global log sink
```

**Migration Guide**:

- Backend services: Use `init_logging(process_type="main")`
- Device sync scripts: Use `init_logging(process_type="device")`
- Subprocess scripts: Use `init_logging(process_type="subprocess")`

#### 1.2 Standardize on Loguru in Backend

**Problem**: Backend services use stdlib logging, causing conflicts with loguru.

**Solution**: Create backend logging wrapper and intercept stdlib logs.

**Implementation**:

```python
# backend/core/logging.py
from loguru import logger
import logging

class InterceptHandler(logging.Handler):
    """Intercept stdlib logging and route to loguru."""
    def emit(self, record):
        # Get corresponding loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def setup_backend_logging():
    """Initialize loguru for backend with stdlib interception."""
    # Remove default handler
    logger.remove()

    # Add console handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

    # Intercept stdlib logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0)

    # Intercept uvicorn logs
    for log_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        logging_logger = logging.getLogger(log_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False

    return logger

# Usage in backend services
from backend.core.logging import setup_backend_logging
logger = setup_backend_logging()
```

#### 1.3 Add Structured Error Tracking

**Problem**: Errors logged as unstructured text, no aggregation or tracking.

**Solution**: Assign unique error IDs and structured error context.

**Implementation**:

```python
# core/error_tracking.py
import uuid
from dataclasses import dataclass
from typing import Any
from loguru import logger

@dataclass
class ErrorContext:
    error_id: str
    error_type: str
    error_message: str
    device_serial: str | None = None
    customer_name: str | None = None
    stack_trace: str | None = None
    context: dict[str, Any] = None

def log_error(
    error: Exception,
    device_serial: str | None = None,
    customer_name: str | None = None,
    **context: Any,
) -> str:
    """Log error with structured context and unique ID."""
    error_id = str(uuid.uuid4())[:8]

    error_ctx = ErrorContext(
        error_id=error_id,
        error_type=type(error).__name__,
        error_message=str(error),
        device_serial=device_serial,
        customer_name=customer_name,
        stack_trace=traceback.format_exc(),
        context=context or {},
    )

    # Structured logging (JSON)
    logger.bind(
        error_id=error_id,
        error_type=error_ctx.error_type,
        device=device_serial,
        customer=customer_name,
    ).error(
        f"[{error_id}] {error_ctx.error_type}: {error_ctx.error_message}",
    )

    # Also log to dedicated error sink
    logger.bind(
        error_context=error_ctx.__dict__,
    ).error("error_occurred")

    return error_id
```

### Phase 2: Enhanced Observability (Weeks 2-3)

#### 2.1 Centralized Log Collector Service

**Purpose**: Aggregate logs from all processes in real-time without file locks.

**Architecture**:

```
┌─────────────────┐     stdout/stderr      ┌──────────────────────┐
│  Device Process │ ──────────────────────> │                      │
└─────────────────┘                         │                      │
┌─────────────────┐     stdout/stderr      │   Log Collector      │
│  Device Process │ ──────────────────────> │   (FastAPI Service)  │
└─────────────────┘                         │                      │
┌─────────────────┐     stdout/stderr      │                      │
│  Backend Main   │ ──────────────────────> │                      │
└─────────────────┘                         └──────────┬───────────┘
                                                        │
                                                        ▼
                                              ┌─────────────────────┐
                                              │   Log Aggregation   │
                                              │   - Deduplication   │
                                              │   - Enrichment      │
                                              │   - Indexing        │
                                              └──────────┬──────────┘
                                                         │
                        ┌────────────────────────────────┼────────────────────────┐
                        ▼                                ▼                        ▼
                ┌───────────────┐              ┌───────────────┐      ┌───────────────┐
                │  File Storage │              │  WebSocket    │      │  Metrics/     │
                │  (per device) │              │  Streaming    │      │  Tracing      │
                └───────────────┘              └───────────────┘      └───────────────┘
```

**Implementation**: See `backend/services/log_collector.py` (to be created)

#### 2.2 Log Health Check Endpoint

**Purpose**: Monitor log system health and detect issues.

**Endpoint**: `GET /api/logs/health`

**Response**:

```json
{
  "status": "healthy",
  "log_directory": "D:\\111\\android_run_test-backup\\logs",
  "disk_space": "2.4 GB free",
  "active_devices": [
    {
      "serial": "9586492623004ZE",
      "log_file": "default-9586492623004ZE.log",
      "size_mb": 1.2,
      "last_modified": "2026-02-09T14:55:19",
      "status": "active"
    }
  ],
  "issues": [
    {
      "severity": "warning",
      "message": "Log file retention exceeding 30 days for 2 files"
    }
  ]
}
```

#### 2.3 Automatic Log Archival

**Purpose**: Compress and archive old logs to save disk space.

**Implementation**:

```python
# services/log_archiver.py
import gzip
from pathlib import Path
from datetime import datetime, timedelta

class LogArchiver:
    """Automatically compress and archive old logs."""

    def __init__(self, log_dir: Path, archive_after_days: int = 7):
        self.log_dir = log_dir
        self.archive_after_days = archive_after_days
        self.archive_dir = log_dir / "archive"
        self.archive_dir.mkdir(exist_ok=True)

    def archive_old_logs(self):
        """Compress logs older than threshold."""
        cutoff = datetime.now() - timedelta(days=self.archive_after_days)

        for log_file in self.log_dir.glob("*.log"):
            if self._should_archive(log_file, cutoff):
                self._compress(log_file)

    def _compress(self, log_file: Path):
        """Compress single log file."""
        archive_path = self.archive_dir / f"{log_file.name}.gz"

        with open(log_file, 'rb') as f_in:
            with gzip.open(archive_path, 'wb') as f_out:
                f_out.writelines(f_in)

        log_file.unlink()
        logger.info(f"Archived {log_file.name} -> {archive_path.name}")
```

**Schedule**: Run daily via FastAPI background tasks.

### Phase 3: Advanced Observability (Month 2)

#### 3.1 Metrics Collection

**Purpose**: Collect operational metrics beyond business events.

**Metrics to Track**:

- **Throughput**: Messages/second, customers/minute
- **Latency**: Device response time, sync duration
- **Errors**: Error rate by type, device error count
- **Resources**: Memory usage, droidrun connection pool

**Implementation**:

```python
# core/metrics.py
from prometheus_client import Counter, Histogram, Gauge
from prometheus_client import start_http_server

# Define metrics
messages_processed = Counter(
    'wecom_messages_total',
    'Total messages processed',
    ['device', 'status']
)

sync_duration = Histogram(
    'wecom_sync_duration_seconds',
    'Sync operation duration',
    ['device']
)

active_connections = Gauge(
    'wecom_droidrun_connections',
    'Active droidrun connections',
    ['device']
)

# Expose metrics endpoint
def start_metrics_server(port: int = 9090):
    """Start Prometheus metrics server."""
    start_http_server(port)
    logger.info(f"Metrics server started on port {port}")
```

#### 3.2 Distributed Tracing

**Purpose**: Track requests across multiple processes/services.

**Implementation**: OpenTelemetry integration

```python
# core/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

def setup_tracing(service_name: str):
    """Initialize OpenTelemetry tracing."""
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer(__name__)

    # Export to Jaeger (or local file)
    exporter = JaegerExporter(
        agent_host_name="localhost",
        agent_port=6831,
    )

    span_processor = BatchSpanProcessor(exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)

    return tracer
```

#### 3.3 Alerting System

**Purpose**: Proactive notifications for critical issues.

**Alert Rules**:

- **Device Offline**: No logs from device for 5+ minutes
- **High Error Rate**: >10 errors in 1 minute from a device
- **Sync Stalled**: No progress updates for 10+ minutes
- **Disk Space**: <1 GB free in logs directory

**Implementation**:

```python
# services/alerting.py
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class AlertRule:
    name: str
    condition: callable  # Returns True if alert should fire
    severity: str  # "info", "warning", "critical"
    cooldown_minutes: int = 5

class AlertManager:
    """Manage alert rules and notifications."""

    def __init__(self):
        self.rules: list[AlertRule] = []
        self.last_alerted: dict[str, datetime] = {}

    def add_rule(self, rule: AlertRule):
        """Add alert rule."""
        self.rules.append(rule)

    def check_rules(self, context: dict):
        """Evaluate all rules and send alerts if needed."""
        for rule in self.rules:
            if rule.condition(context):
                if self._should_alert(rule):
                    self._send_alert(rule, context)

    def _send_alert(self, rule: AlertRule, context: dict):
        """Send alert notification."""
        # Email, WebSocket push, etc.
        logger.warning(f"ALERT [{rule.severity}]: {rule.name}")
```

## Implementation Priority

| Priority | Task                              | Effort   | Impact                             |
| -------- | --------------------------------- | -------- | ---------------------------------- |
| 🔴 P0    | Remove global log file            | 2 hours  | Eliminates Windows lock contention |
| 🔴 P0    | Backend stdlib → loguru migration | 4 hours  | Fixes framework conflicts          |
| 🟡 P1    | Structured error tracking         | 6 hours  | Enables error aggregation          |
| 🟡 P1    | Log health check endpoint         | 3 hours  | Operational visibility             |
| 🟢 P2    | Log collector service             | 16 hours | Centralized log management         |
| 🟢 P2    | Automatic archival                | 8 hours  | Disk space optimization            |
| 🔵 P3    | Prometheus metrics                | 12 hours | Operational metrics                |
| 🔵 P3    | OpenTelemetry tracing             | 16 hours | Request tracing                    |
| 🔵 P3    | Alerting system                   | 12 hours | Proactive monitoring               |

## Migration Path

### Week 1: Critical Fixes

1. Remove global log file from `logging.py`
2. Update all `init_logging()` calls with `process_type` parameter
3. Create `backend/core/logging.py` with stdlib interception
4. Test multi-device parallel sync on Windows

### Week 2-3: Enhanced Observability

1. Implement error tracking module
2. Add log health check endpoint
3. Create log archival background task
4. Update desktop app to display error IDs

### Month 2: Advanced Features

1. Add Prometheus metrics server
2. Integrate OpenTelemetry tracing
3. Implement alerting system
4. Create log analytics dashboard

## Risks and Mitigations

| Risk                               | Impact | Mitigation                                  |
| ---------------------------------- | ------ | ------------------------------------------- |
| Breaking existing log readers      | High   | Maintain backward-compatible log format     |
| Performance overhead               | Medium | Profile logging overhead, keep <5% CPU      |
| Disk space growth                  | Medium | Implement aggressive archival after Phase 2 |
| Complex dependency (OpenTelemetry) | Low    | Optional feature, not core functionality    |

## Success Metrics

- **Zero lock contention**: No more "file locked" errors during parallel sync
- **Unified framework**: 100% loguru usage (no stdlib logging)
- **Error visibility**: All errors tracked with unique IDs
- **Operational insight**: Health check endpoint provides real-time status
- **Disk efficiency**: Automatic archival keeps log directory <5 GB

## Open Questions

1. **Log retention**: Is 30 days sufficient, or do we need longer retention for compliance?
2. **External integrations**: Should logs be sent to external services (Splunk, ELK, Datadog)?
3. **Real-time vs historical**: Does the desktop app need historical log viewing, or is real-time streaming sufficient?
4. **Metrics backend**: Should we use Prometheus, or a simpler solution?

## References

- Current logging implementation: `src/wecom_automation/core/logging.py`
- Metrics logger: `src/wecom_automation/core/metrics_logger.py`
- WebSocket log streaming: `wecom-desktop/backend/routers/logs.py`
- Subprocess logging: `wecom-desktop/backend/scripts/realtime_reply_process.py`
