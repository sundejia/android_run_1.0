# Admin Actions Backup Service

> Date: 2026-02-01
> Status: ✅ Complete

## Overview

Automatic periodic backup service for `settings/admin_actions.xlsx` to prevent data loss. The service runs as a background task that copies the source file to a backup file at configurable intervals.

## Architecture

### Components

| File                         | Purpose                                           |
| ---------------------------- | ------------------------------------------------- |
| `services/backup_service.py` | Background service that performs periodic backups |
| `routers/backup.py`          | REST API endpoints for backup management          |
| `main.py`                    | Startup/shutdown integration                      |

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Application Startup                        │
│                                                                      │
│  1. BackupService starts in lifespan handler                       │
│  2. Performs initial backup immediately                           │
│  3. Schedules periodic backups (default: 30 minutes)               │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Backup Loop (Background Task)                    │
│                                                                      │
│  Every 30 minutes:                                                  │
│    1. Check if source file exists                                   │
│    2. Copy admin_actions.xlsx → admin_actions_backup.xlsx         │
│    3. Update last_backup_time                                       │
│    4. Log success/failure                                           │
└─────────────────────────────────────────────────────────────────────┘
```

## Configuration

### Default Settings

```python
source_file = "settings/admin_actions.xlsx"      # Source file
backup_file = "settings/admin_actions_backup.xlsx"  # Backup file
interval_minutes = 30                           # Backup interval
```

### File Paths

Both files are located in the project root's `settings/` directory:

- Source: `<project_roo../03-impl-and-arch/key-modules/admin_actions.xlsx`
- Backup: `<project_roo../03-impl-and-arch/key-modules/admin_actions_backup.xlsx`

## API Endpoints

### GE../03-impl-and-arch/key-modules/backup/status

Get current backup service status.

**Response:**

```json
{
  "running": true,
  "source_file": "/path/../03-impl-and-arch/key-modules/admin_actions.xlsx",
  "backup_file": "/path/../03-impl-and-arch/key-modules/admin_actions_backup.xlsx",
  "interval_minutes": 30,
  "source_exists": true,
  "backup_exists": true,
  "last_backup_time": "2026-02-01T15:30:00",
  "backup_size": 12345,
  "backup_modified": "2026-02-01T15:30:00"
}
```

### POS../03-impl-and-arch/key-modules/backup/trigger

Trigger an immediate backup (manual trigger).

**Response:**

```json
{
  "success": true,
  "message": "Backup completed successfully"
}
```

**Error Response (source file missing):**

```json
{
  "success": false,
  "message": "Source file does not exist: admin_actions.xlsx"
}
```

## Python API

### Using BackupService directly

```python
from services.backup_service import get_admin_actions_backup_service

# Get singleton instance
backup_service = get_admin_actions_backup_service()

# Start the background service
backup_service.start()

# Trigger manual backup
success = backup_service.backup_now()
if success:
    print("Backup completed")

# Get status
status = backup_service.get_status()
print(f"Running: {status['running']}")
print(f"Last backup: {status['last_backup_time']}")

# Stop the service (graceful shutdown)
await backup_service.stop()
```

## Lifecycle

### Application Startup

In `main.py` lifespan handler:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    backup_service = get_admin_actions_backup_service()
    backup_service.start()
    print(f"[startup] Backup service started (interval: {backup_service.interval_minutes} min)")

    yield

    # Shutdown
    await backup_service.stop()
    print("[shutdown] Backup service stopped")
```

### Backup Algorithm

```python
def backup_now(self) -> bool:
    """
    Perform an immediate backup (copy and overwrite).

    Returns:
        True if backup succeeded, False otherwise
    """
    # 1. Check if source file exists
    if not self.source_file.exists():
        logger.warning(f"Source file does not exist: {self.source_file}")
        return False

    # 2. Ensure parent directory exists
    self.backup_file.parent.mkdir(parents=True, exist_ok=True)

    # 3. Copy and overwrite
    shutil.copy2(self.source_file, self.backup_file)
    self._last_backup_time = datetime.now()

    return True
```

## Error Handling

### Source File Missing

If `admin_actions.xlsx` doesn't exist:

- Service continues running
- Returns `False` from `backup_now()`
- Logs warning message
- API trigger returns error response

### Backup Failures

If copy operation fails:

- Exception caught and logged
- Service continues running (will retry next interval)
- No crash or interruption

## Logging

Log format:

```
[backup] Started backup loop: admin_actions.xlsx -> admin_actions_backup.xlsx (interval: 30 min)
[backup] Copied admin_actions.xlsx -> admin_actions_backup.xlsx
[backup] Backup loop stopped
```

## Integration with Git

Both backup files are **excluded** from git (in `.gitignore`):

```
settings/admin_actions.json
settings/admin_actions.xlsx
settings/admin_actions_backup.xlsx
```

This ensures:

- Sensitive admin action data is not tracked
- Local backups are not committed
- Each developer/machine has their own backup

## Related Documentation

- [Admin Actions Excel Migration](implementation/admin_actions_excel_migration.md)
- [Git Ignore Configuration](../.gitignore)
