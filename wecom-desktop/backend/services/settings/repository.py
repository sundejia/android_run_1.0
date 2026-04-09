"""
Settings Repository - 数据库操作层

提供设置的 CRUD 操作。
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

from .models import SettingRecord, ValueType
from .defaults import SETTING_DEFINITIONS, get_default_value, get_value_type
from wecom_automation.core.performance import InstrumentedConnection


class SettingsRepository:
    """设置数据库操作类"""

    # Schema definitions
    SCHEMA_SETTINGS = """
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        key TEXT NOT NULL,
        value_type TEXT NOT NULL,
        value_string TEXT,
        value_int INTEGER,
        value_float REAL,
        value_bool INTEGER,
        value_json TEXT,
        description TEXT,
        is_sensitive INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(category, key)
    );
    """

    SCHEMA_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);
    CREATE INDEX IF NOT EXISTS idx_settings_category_key ON settings(category, key);
    """

    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self._db_path = db_path
        self._logger = logger or logging.getLogger(__name__)
        self._ensure_tables()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(self._db_path, factory=InstrumentedConnection)
        conn.row_factory = sqlite3.Row

        # Enable foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON")

        # Enable WAL mode for better concurrent read/write performance
        conn.execute("PRAGMA journal_mode = WAL")

        # Set busy_timeout to 30 seconds - wait instead of failing immediately
        conn.execute("PRAGMA busy_timeout = 30000")

        # Use NORMAL synchronous mode for balance between performance and safety
        conn.execute("PRAGMA synchronous = NORMAL")

        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Generator[Tuple[sqlite3.Connection, sqlite3.Cursor], None, None]:
        """获取事务（上下文管理器）"""
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                yield conn, cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _ensure_tables(self) -> None:
        """确保表存在"""
        with self._transaction() as (conn, cursor):
            cursor.executescript(self.SCHEMA_SETTINGS)
            cursor.execute("DROP TABLE IF EXISTS settings_history")
            cursor.executescript(self.SCHEMA_INDEXES)
        self._logger.debug("Settings tables ensured")

    def _value_to_columns(self, value: Any, value_type: str) -> Dict[str, Any]:
        """将值转换为对应的数据库列"""
        columns = {
            "value_string": None,
            "value_int": None,
            "value_float": None,
            "value_bool": None,
            "value_json": None,
        }

        if value_type == ValueType.STRING.value:
            columns["value_string"] = str(value) if value is not None else None
        elif value_type == ValueType.INT.value:
            columns["value_int"] = int(value) if value is not None else None
        elif value_type == ValueType.FLOAT.value:
            columns["value_float"] = float(value) if value is not None else None
        elif value_type == ValueType.BOOLEAN.value:
            columns["value_bool"] = 1 if value else 0
        elif value_type == ValueType.JSON.value:
            columns["value_json"] = json.dumps(value) if value is not None else None
        else:
            columns["value_string"] = str(value) if value is not None else None

        return columns

    def _get_value_from_row(self, row: sqlite3.Row) -> Any:
        """从数据库行获取值"""
        value_type = row["value_type"]

        if value_type == ValueType.STRING.value:
            return row["value_string"]
        elif value_type == ValueType.INT.value:
            return row["value_int"]
        elif value_type == ValueType.FLOAT.value:
            return row["value_float"]
        elif value_type == ValueType.BOOLEAN.value:
            return bool(row["value_bool"])
        elif value_type == ValueType.JSON.value:
            return json.loads(row["value_json"]) if row["value_json"] else None
        else:
            return row["value_string"]

    # ============================================================================
    # CRUD Operations
    # ============================================================================

    def get(self, category: str, key: str) -> Optional[SettingRecord]:
        """获取单个设置"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM settings WHERE category = ? AND key = ?", (category, key))
            row = cursor.fetchone()
            if row:
                return SettingRecord.from_row(row)
            return None

    def get_value(self, category: str, key: str, default: Any = None) -> Any:
        """获取设置值（如果不存在返回默认值）"""
        record = self.get(category, key)
        if record:
            return record.value
        # 如果没有记录，尝试从默认值获取
        db_default = get_default_value(category, key)
        return db_default if db_default is not None else default

    def get_category(self, category: str) -> Dict[str, Any]:
        """获取指定类别的所有设置"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM settings WHERE category = ?", (category,))
            rows = cursor.fetchall()

            result = {}
            for row in rows:
                result[row["key"]] = self._get_value_from_row(row)
            return result

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """获取所有设置，按类别分组"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM settings ORDER BY category, key")
            rows = cursor.fetchall()

            result: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                category = row["category"]
                if category not in result:
                    result[category] = {}
                result[category][row["key"]] = self._get_value_from_row(row)
            return result

    def set(
        self,
        category: str,
        key: str,
        value: Any,
        changed_by: str = "api",
        description: Optional[str] = None,
        is_sensitive: bool = False,
    ) -> SettingRecord:
        """设置值（不存在则创建，存在则更新）"""
        value_type = get_value_type(category, key)
        columns = self._value_to_columns(value, value_type)

        with self._transaction() as (conn, cursor):
            cursor.execute("SELECT * FROM settings WHERE category = ? AND key = ?", (category, key))
            existing = cursor.fetchone()

            if existing:
                # 更新
                cursor.execute(
                    """
                    UPDATE settings SET
                        value_string = ?,
                        value_int = ?,
                        value_float = ?,
                        value_bool = ?,
                        value_json = ?,
                        description = COALESCE(?, description),
                        is_sensitive = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE category = ? AND key = ?
                    """,
                    (
                        columns["value_string"],
                        columns["value_int"],
                        columns["value_float"],
                        columns["value_bool"],
                        columns["value_json"],
                        description,
                        1 if is_sensitive else 0,
                        category,
                        key,
                    ),
                )
            else:
                # 插入
                cursor.execute(
                    """
                    INSERT INTO settings (
                        category, key, value_type,
                        value_string, value_int, value_float, value_bool, value_json,
                        description, is_sensitive
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        category,
                        key,
                        value_type,
                        columns["value_string"],
                        columns["value_int"],
                        columns["value_float"],
                        columns["value_bool"],
                        columns["value_json"],
                        description,
                        1 if is_sensitive else 0,
                    ),
                )

        # 返回更新后的记录
        return self.get(category, key)

    def set_many(
        self,
        category: str,
        settings: Dict[str, Any],
        changed_by: str = "api",
    ) -> Dict[str, Any]:
        """批量设置值"""
        for key, value in settings.items():
            self.set(category, key, value, changed_by)
        return self.get_category(category)

    def delete(self, category: str, key: str) -> bool:
        """删除设置"""
        with self._transaction() as (conn, cursor):
            cursor.execute("DELETE FROM settings WHERE category = ? AND key = ?", (category, key))
            return cursor.rowcount > 0

    def reset_to_default(self, category: str, key: str, changed_by: str = "api") -> Optional[SettingRecord]:
        """重置为默认值"""
        default = get_default_value(category, key)
        if default is not None:
            return self.set(category, key, default, changed_by)
        return None

    def reset_category(self, category: str, changed_by: str = "api") -> Dict[str, Any]:
        """重置整个类别为默认值"""
        for cat, key, _, default, desc, sensitive in SETTING_DEFINITIONS:
            if cat == category:
                self.set(category, key, default, changed_by, desc, sensitive)
        return self.get_category(category)

    # ============================================================================
    # Initialization
    # ============================================================================

    def initialize_defaults(self, overwrite: bool = False) -> int:
        """初始化默认设置值"""
        count = 0
        for category, key, value_type, default, description, is_sensitive in SETTING_DEFINITIONS:
            existing = self.get(category, key)
            if existing is None or overwrite:
                self.set(
                    category,
                    key,
                    default,
                    changed_by="init",
                    description=description,
                    is_sensitive=is_sensitive,
                )
                count += 1
        self._logger.info(f"Initialized {count} settings with default values")
        return count

    def sync_definition_metadata(self) -> int:
        """Refresh description/is_sensitive from SETTING_DEFINITIONS when they drift (e.g. fixed mojibake)."""
        updated = 0
        with self._transaction() as (conn, cursor):
            for category, key, _, _, description, is_sensitive in SETTING_DEFINITIONS:
                want_sens = 1 if is_sensitive else 0
                cursor.execute(
                    """
                    UPDATE settings
                    SET description = ?, is_sensitive = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE category = ? AND key = ?
                      AND (IFNULL(description, '') != IFNULL(?, '')
                           OR IFNULL(is_sensitive, 0) != ?)
                    """,
                    (description, want_sens, category, key, description, want_sens),
                )
                updated += cursor.rowcount
        if updated:
            self._logger.info("Synced settings metadata from definitions (%s rows updated)", updated)
        return updated

    def has_initialized(self) -> bool:
        """检查是否已初始化"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM settings")
            count = cursor.fetchone()[0]
            return count > 0
