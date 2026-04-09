#!/usr/bin/env python3
"""
Log File Health Check Script

Checks per-device log files in the logs/ directory for:
- File existence and size
- Common error patterns (permission denied, file locked, etc.)
- Last modification time

Usage:
    python scripts/check_log_health.py
"""

import re
from datetime import datetime
from pathlib import Path


def check_log_file(log_path: Path) -> dict:
    """
    Check a single log file for issues.

    Args:
        log_path: Path to log file

    Returns:
        Dictionary with health status and details
    """
    if not log_path.exists():
        return {"status": "missing", "errors": ["File does not exist"]}

    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except PermissionError:
        return {"status": "error", "errors": ["Permission denied reading file"]}
    except Exception as e:
        return {"status": "error", "errors": [f"Error reading file: {e}"]}

    errors = []

    # Check for common error patterns
    error_patterns = [
        (r"PermissionError", "File permission error"),
        (r"Permission denied", "File access denied"),
        (r"file locked", "File locked by another process"),
        (r"Access is denied", "Windows access denied"),
        (r"cannot open file", "File open failure"),
        (r"IOError", "I/O error"),
        (r"OSError", "OS error"),
        (r"BrokenPipeError", "Broken pipe (process terminated?)"),
    ]

    for pattern, description in error_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # Count occurrences
            count = len(re.findall(pattern, text, re.IGNORECASE))
            errors.append(f"{description} (found {count} time(s))")

    # Get file stats
    try:
        stat = log_path.stat()
        size_kb = round(stat.st_size / 1024, 2)
        last_modified = datetime.fromtimestamp(stat.st_mtime)

        return {
            "status": "healthy" if not errors else "unhealthy",
            "size_kb": size_kb,
            "last_modified": last_modified,
            "errors": errors,
        }
    except Exception as e:
        return {"status": "error", "errors": [f"Error getting file stats: {e}"]}


def main():
    """Main entry point."""
    import sys

    # Get project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    logs_dir = project_root / "logs"

    if not logs_dir.exists():
        print(f"[ERROR] Logs directory not found: {logs_dir}")
        sys.exit(1)

    print(f"Checking log files in {logs_dir.relative_to(project_root)}/\n")

    # All *-*.log files directly under logs/ (not metrics/)
    device_logs = sorted(p for p in logs_dir.glob("*-*.log") if p.is_file())

    if not device_logs:
        print("[OK] No per-device *.log files in logs/ (nothing to check)")
        return 0

    print("Device logs:")
    for log_file in device_logs:
        result = check_log_file(log_file)
        status_icon = (
            "[OK]"
            if result["status"] == "healthy"
            else "[ERROR]"
            if result["status"] == "unhealthy"
            else "[WARN]"
        )
        size_kb = result.get("size_kb", 0)
        print(f"{status_icon} {log_file.name}: {size_kb:.2f} KB")

        if result.get("errors"):
            for error in result["errors"]:
                print(f"      [!] {error}")

    # Summary
    print()
    healthy = sum(1 for log in device_logs if check_log_file(log)["status"] == "healthy")
    total = len(device_logs)

    if healthy == total:
        print(f"[OK] All log files are healthy ({healthy}/{total})")
        return 0
    else:
        print(f"[WARN] Some log files have issues ({healthy}/{total} healthy)")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
