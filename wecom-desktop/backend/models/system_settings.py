"""
System Settings Model

Used for persistent storage of system configurations, including language preferences.
"""

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional

from i18n.translations import DEFAULT_LANGUAGE

try:
    from wecom_automation.core.config import get_default_db_path
except ImportError:
    # Fallback if wecom_automation is not in path (e.g. simplified environment)
    def get_default_db_path():
        from utils.path_utils import get_project_root
        return get_project_root() / "wecom_conversations.db"


class SystemSettingsModel:
    """System Settings Database Model"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = get_default_db_path()
        self._db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """Ensure settings table exists"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get setting value"""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def set(self, key: str, value: str) -> bool:
        """Set value"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """,
                (key, value, datetime.now().isoformat()),
            )
            conn.commit()
            return True

    def get_language(self) -> str:
        """Get language setting"""
        return self.get("language", DEFAULT_LANGUAGE)

    def set_language(self, language: str) -> bool:
        """Set language"""
        return self.set("language", language)
