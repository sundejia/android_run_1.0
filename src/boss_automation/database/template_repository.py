"""Repository for the ``greeting_templates`` table.

Templates are scoped by a ``scenario`` enum (``first_greet`` |
``reply`` | ``reengage``) and uniqueness is enforced on
``(name, scenario)``. The repository deliberately keeps logic minimal:
selection (which template best fits an inbound message) lives in the
service layer, not here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from boss_automation.database.schema import ensure_schema

_VALID_SCENARIOS: Final[frozenset[str]] = frozenset({"first_greet", "reply", "reengage"})


@dataclass(frozen=True, slots=True)
class TemplateRecord:
    id: int
    name: str
    scenario: str
    content: str
    is_default: bool
    variables_json: str | None = None


class TemplateRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        ensure_schema(self._db_path)

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def insert(
        self,
        *,
        name: str,
        scenario: str,
        content: str,
        is_default: bool = False,
        variables_json: str | None = None,
    ) -> int:
        if scenario not in _VALID_SCENARIOS:
            raise ValueError(f"invalid scenario {scenario!r}; expected one of {sorted(_VALID_SCENARIOS)}")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO greeting_templates
                    (name, scenario, content, is_default, variables_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, scenario, content, 1 if is_default else 0, variables_json),
            )
            assert cursor.lastrowid is not None
            return int(cursor.lastrowid)

    def update(
        self,
        template_id: int,
        *,
        content: str | None = None,
        is_default: bool | None = None,
        variables_json: str | None = None,
    ) -> None:
        sets: list[str] = []
        values: list[object] = []
        if content is not None:
            sets.append("content = ?")
            values.append(content)
        if is_default is not None:
            sets.append("is_default = ?")
            values.append(1 if is_default else 0)
        if variables_json is not None:
            sets.append("variables_json = ?")
            values.append(variables_json)
        if not sets:
            return
        sets.append("updated_at = CURRENT_TIMESTAMP")
        values.append(template_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE greeting_templates SET {', '.join(sets)} WHERE id = ?",
                values,
            )

    def delete(self, template_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM greeting_templates WHERE id = ?", (template_id,))
            return cursor.rowcount > 0

    def get_by_id(self, template_id: int) -> TemplateRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, scenario, content, is_default, variables_json
                FROM greeting_templates WHERE id = ?
                """,
                (template_id,),
            ).fetchone()
        return _to_record(row) if row else None

    def list_by_scenario(self, scenario: str) -> list[TemplateRecord]:
        if scenario not in _VALID_SCENARIOS:
            raise ValueError(f"invalid scenario {scenario!r}")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, scenario, content, is_default, variables_json
                FROM greeting_templates WHERE scenario = ? ORDER BY id ASC
                """,
                (scenario,),
            ).fetchall()
        return [_to_record(r) for r in rows]

    def get_default(self, scenario: str) -> TemplateRecord | None:
        if scenario not in _VALID_SCENARIOS:
            raise ValueError(f"invalid scenario {scenario!r}")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, scenario, content, is_default, variables_json
                FROM greeting_templates
                WHERE scenario = ? AND is_default = 1
                ORDER BY id ASC LIMIT 1
                """,
                (scenario,),
            ).fetchone()
        return _to_record(row) if row else None


def _to_record(row: sqlite3.Row) -> TemplateRecord:
    return TemplateRecord(
        id=int(row["id"]),
        name=row["name"],
        scenario=row["scenario"],
        content=row["content"],
        is_default=bool(row["is_default"]),
        variables_json=row["variables_json"],
    )
