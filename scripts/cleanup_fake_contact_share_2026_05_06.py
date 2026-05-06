#!/usr/bin/env python3
"""
One-shot cleanup for the 2026-05-06 22:58 fake-success contact-share record.

Background
----------
On 2026-05-06 22:58, ContactShareService logged
``Action auto_contact_share completed: success`` for customer
``B2604270540-[重复(保底正常)]`` even though the share never actually
reached the WeCom UI past the attach panel — the page-state envelope
introduced after this incident now blocks that path. The fake-success
write to ``media_action_contact_shares`` poisons future triggers because
``contact_already_shared()`` will short-circuit any retry for that
``(device, customer, contact)`` triple.

This script removes only the affected row so the customer can be retried
on the next image trigger. Other historical rows are left untouched per
the agreed cleanup scope (wipe_recent).

Usage
-----
    python scripts/cleanup_fake_contact_share_2026_05_06.py            # apply
    python scripts/cleanup_fake_contact_share_2026_05_06.py --dry-run  # preview
    python scripts/cleanup_fake_contact_share_2026_05_06.py --db /custom/path.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from wecom_automation.database.schema import get_db_path  # noqa: E402

# Identity of the fake-success row to remove. Kept as constants so an
# operator running this script later can audit exactly what's targeted.
TARGET_DEVICE_SERIAL = "10AE9P1DTT002LE"
TARGET_CUSTOMER_NAME = "B2604270540-[重复(保底正常)]"
TARGET_CONTACT_NAME = "孙德家"

# SQLite ``CURRENT_TIMESTAMP`` writes UTC — the 22:58 Asia/Shanghai event
# lands as 14:58 in the table. Match BOTH so this script is robust against
# either-timezone environments and a re-run would still no-op cleanly.
TARGET_CREATED_AT_PREFIXES = ("2026-05-06 14:58", "2026-05-06 22:58")


def _build_clause() -> tuple[str, list]:
    placeholders = " OR ".join("created_at LIKE ?" for _ in TARGET_CREATED_AT_PREFIXES)
    where = (
        "device_serial = ? "
        "AND customer_name = ? "
        "AND contact_name = ? "
        f"AND ({placeholders})"
    )
    params = [TARGET_DEVICE_SERIAL, TARGET_CUSTOMER_NAME, TARGET_CONTACT_NAME]
    params.extend(prefix + "%" for prefix in TARGET_CREATED_AT_PREFIXES)
    return where, params


SELECT_SQL_TEMPLATE = """
    SELECT id, device_serial, customer_name, contact_name, kefu_name, status, created_at
      FROM media_action_contact_shares
     WHERE {where}
     ORDER BY id
"""

DELETE_SQL_TEMPLATE = """
    DELETE FROM media_action_contact_shares
     WHERE {where}
"""


def _format_row(row: sqlite3.Row) -> str:
    return (
        f"  id={row['id']:<5} device={row['device_serial']} "
        f"customer={row['customer_name']!r} contact={row['contact_name']!r} "
        f"kefu={row['kefu_name']!r} status={row['status']!r} "
        f"created_at={row['created_at']!r}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--db",
        default=None,
        help="Path to wecom_conversations.db (defaults to project default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching rows without deleting.",
    )
    args = parser.parse_args()

    db_path = str(get_db_path(args.db))
    where, params = _build_clause()
    print(f"Database: {db_path}")
    print(
        "Target: device={!r} customer={!r} contact={!r} created_at LIKE any of {!r}".format(
            TARGET_DEVICE_SERIAL,
            TARGET_CUSTOMER_NAME,
            TARGET_CONTACT_NAME,
            [p + "%" for p in TARGET_CREATED_AT_PREFIXES],
        )
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(SELECT_SQL_TEMPLATE.format(where=where), params).fetchall()

        if not rows:
            print("No matching rows. Nothing to do.")
            return 0

        print(f"Matched {len(rows)} row(s):")
        for row in rows:
            print(_format_row(row))

        if args.dry_run:
            print("\n--dry-run set; no rows deleted.")
            return 0

        cur = conn.execute(DELETE_SQL_TEMPLATE.format(where=where), params)
        conn.commit()
        print(f"\nDeleted {cur.rowcount} row(s). Customer can now be retried on next image.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
