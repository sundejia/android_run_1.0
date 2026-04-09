"""
Blacklist Service - Framework-level blacklist management.

This service provides blacklist functionality for the sync framework,
accessing the database directly without depending on backend code.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from wecom_automation.database.schema import get_db_path

logger = logging.getLogger("wecom_automation.blacklist")


def _normalize_channel(channel: str | None) -> str | None:
    """Normalize channel text to reduce cross-view mismatches."""
    if channel is None:
        return None
    normalized = channel.strip().replace("＠", "@")
    return normalized or None


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _has_conversation_tables(db_path: str) -> bool:
    try:
        conn = sqlite3.connect(db_path)
        try:
            return all(_table_exists(conn, table_name) for table_name in ("customers", "messages", "kefus"))
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _ensure_backend_import_path() -> None:
    backend_path = Path(__file__).parent.parent.parent.parent / "wecom-desktop" / "backend"
    if backend_path.exists() and str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))


def _resolve_device_customer_db_path(control_db_path: str, device_serial: str) -> str:
    """Resolve the conversation DB that stores customer/message rows for a device."""
    _ensure_backend_import_path()
    try:
        from services.conversation_storage import get_device_conversation_db_path

        candidate = get_device_conversation_db_path(device_serial)
        candidate_path = str(candidate)
        if Path(candidate_path).exists() and _has_conversation_tables(candidate_path):
            return candidate_path
    except Exception:
        pass

    return control_db_path


class BlacklistChecker:
    """
    Blacklist checker for sync framework.

    Provides thread-safe blacklist checking with caching and multi-process
    synchronization via version detection.
    """

    _cache: dict[str, set[tuple[str, str | None]]] = {}
    _cache_loaded: bool = False
    _cache_version: int = 0  # Timestamp-based version for multi-process sync

    @classmethod
    def _get_db_version(cls, db_path: str) -> int:
        """Get current database version based on max updated_at timestamp."""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(
                    CAST(strftime('%s', MAX(updated_at)) AS INTEGER),
                    0
                ) as version
                FROM blacklist
            """)
            row = cursor.fetchone()
            conn.close()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    @classmethod
    def is_cache_stale(cls) -> bool:
        """Check if cache is stale compared to database version."""
        if not cls._cache_loaded:
            return True
        db_path = str(get_db_path())
        db_version = cls._get_db_version(db_path)
        return db_version > cls._cache_version

    @classmethod
    def load_cache(cls) -> None:
        """Load blacklist into memory cache."""
        db_path = str(get_db_path())
        cls._cache.clear()

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # IMPORTANT: Only load records where is_blacklisted=1
            # This ensures whitelisted users (is_blacklisted=0) are not blocked
            cursor.execute("""
                SELECT device_serial, customer_name, customer_channel
                FROM blacklist
                WHERE is_blacklisted = 1
            """)

            for row in cursor.fetchall():
                device_serial = row["device_serial"]
                customer_name = row["customer_name"]
                customer_channel = row["customer_channel"]

                if device_serial not in cls._cache:
                    cls._cache[device_serial] = set()
                cls._cache[device_serial].add((customer_name, customer_channel))

            # Update cache version from database
            cls._cache_version = cls._get_db_version(db_path)
            conn.close()
            cls._cache_loaded = True
            logger.info(
                f"Loaded {sum(len(s) for s in cls._cache.values())} blacklist entries into cache (version: {cls._cache_version})"
            )

        except Exception as e:
            logger.warning(f"Failed to load blacklist cache: {e}")
            cls._cache = {}
            cls._cache_loaded = False

    @classmethod
    def is_blacklisted(
        cls,
        device_serial: str,
        customer_name: str,
        customer_channel: str | None = None,
        use_cache: bool = False,
        fail_closed: bool = False,
    ) -> bool:
        """
        Check if a user is blacklisted.

        Args:
            device_serial: Device serial number
            customer_name: Customer name
            customer_channel: Optional channel (like @WeChat)
            use_cache: Whether to use cache (default False for real-time accuracy).
                       Set to True for bulk operations where performance matters.
                       When True, cache version is checked and refreshed if stale.
            fail_closed: When True, treat lookup failures as blacklisted so
                         send-related paths prefer skipping over accidental sends.

        Returns:
            True if blacklisted, False otherwise
        """
        _ = _normalize_channel(customer_channel)

        if use_cache:
            # Use cached data with version-based staleness detection
            if not cls._cache_loaded or cls.is_cache_stale():
                cls.load_cache()
            if not cls._cache_loaded:
                if fail_closed:
                    logger.warning(
                        "Blacklist cache unavailable for %s/%s, failing closed",
                        device_serial,
                        customer_name,
                    )
                    return True
                return False

            if device_serial not in cls._cache:
                return False

            entries = cls._cache[device_serial]
            return any(name == customer_name for name, _channel in entries)
        else:
            # Query database directly for real-time accuracy
            # This is essential for Follow-up mode where frontend Block button
            # modifies the database in a separate process (backend API)
            try:
                db_path = str(get_db_path())
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT 1 FROM blacklist
                    WHERE device_serial = ?
                      AND customer_name = ?
                      AND is_blacklisted = 1
                    LIMIT 1
                """,
                    (device_serial, customer_name),
                )

                result = cursor.fetchone() is not None
                conn.close()
                return result

            except Exception as e:
                logger.warning(f"Failed to check blacklist from DB, falling back to cache: {e}")
                if fail_closed:
                    logger.warning(
                        "Blacklist DB lookup failed for %s/%s, failing closed",
                        device_serial,
                        customer_name,
                    )
                    return True
                # Fallback to cache check if DB query fails
                if not cls._cache_loaded or cls.is_cache_stale():
                    cls.load_cache()
                if not cls._cache_loaded:
                    return fail_closed
                if device_serial not in cls._cache:
                    return False
                return any(name == customer_name for name, _channel in cls._cache[device_serial])

    @classmethod
    def invalidate_cache(cls) -> None:
        """Invalidate cache (call after add/remove operations)."""
        cls._cache.clear()
        cls._cache_loaded = False
        cls._cache_version = 0


class BlacklistWriter:
    """
    Blacklist writer for sync framework.

    Provides methods to write scanned users to the blacklist table
    and retrieve whitelisted users for syncing.
    """

    def __init__(self, db_path: str | None = None):
        """
        Initialize blacklist writer.

        Args:
            db_path: Database path, defaults to configured path
        """
        self._db_path = str(get_db_path(db_path))

    @contextmanager
    def _connection(self):
        """Get database connection context."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _get_customer_db_path(self, device_serial: str) -> str:
        """Return the conversation DB that backs customer/message queries."""
        return _resolve_device_customer_db_path(self._db_path, device_serial)

    def _cancel_pending_followups_for_customer(
        self,
        device_serial: str,
        customer_name: str,
        reason: str,
    ) -> int:
        """Cancel pending follow-up attempts stored in the shared control DB."""
        try:
            _ensure_backend_import_path()

            from services.followup.attempts_repository import FollowupAttemptsRepository

            repo = FollowupAttemptsRepository(self._db_path)
            cancelled_count = repo.cancel_attempts_by_customer(
                device_serial=device_serial,
                customer_name=customer_name,
                reason=reason,
            )

            if cancelled_count > 0:
                logger.info("Cancelled %s pending followup attempts for %s", cancelled_count, customer_name)

            return cancelled_count
        except Exception as cancel_error:
            # Cancellation failure doesn't block blacklist updates.
            logger.warning(f"Failed to cancel followup attempts: {cancel_error}")
            return 0

    def _load_blacklist_status_map(
        self,
        device_serial: str,
    ) -> dict[str, dict[str, object]]:
        """Load blacklist status keyed by customer name for a single device."""
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT customer_name, reason, deleted_by_user
                    FROM blacklist
                    WHERE device_serial = ?
                      AND is_blacklisted = 1
                    ORDER BY COALESCE(updated_at, created_at) DESC,
                             COALESCE(created_at, updated_at) DESC,
                             id DESC
                """,
                    (device_serial,),
                )
                status_map: dict[str, dict[str, object]] = {}
                for row in cursor.fetchall():
                    customer_name = row["customer_name"]
                    if customer_name in status_map:
                        continue
                    status_map[customer_name] = {
                        "reason": row["reason"],
                        "deleted_by_user": bool(row["deleted_by_user"])
                        if row["deleted_by_user"] is not None
                        else False,
                    }
                return status_map
        except Exception as exc:
            logger.error("Failed to load blacklist status map for %s: %s", device_serial, exc)
            return {}

    def upsert_scanned_users(
        self,
        device_serial: str,
        users_list: list[dict[str, any]],
    ) -> dict[str, int]:
        """
        Batch upsert scanned users to blacklist table.

        Used in Phase 1 of full sync to write all scanned users to blacklist table.
        - New records: Insert with is_blacklisted=0 (default allowed/whitelisted)
        - Existing records: Update avatar_url, preserve is_blacklisted status

        Args:
            device_serial: Device serial number
            users_list: List of users, each containing:
                - customer_name: User name
                - customer_channel: Channel (optional)
                - avatar_url: Avatar URL (optional)
                - reason: Reason (optional, defaults to "Auto Scan")

        Returns:
            Dict with:
                - inserted: Number of new records inserted
                - updated: Number of existing records updated
                - failed: Number of failed records
        """
        inserted = 0
        updated = 0
        failed = 0

        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                for user in users_list:
                    try:
                        customer_name = user.get("customer_name")
                        customer_channel = _normalize_channel(user.get("customer_channel"))
                        avatar_url = user.get("avatar_url")
                        reason = user.get("reason", "Auto Scan")

                        if not customer_name:
                            logger.warning(f"Skipping user without customer_name: {user}")
                            failed += 1
                            continue

                        # Name is the business identity for blacklist state. Channel
                        # is display metadata and should not create a new row.
                        cursor.execute(
                            """
                            SELECT id FROM blacklist
                            WHERE device_serial = ?
                                AND customer_name = ?
                            ORDER BY updated_at DESC, id DESC
                            LIMIT 1
                        """,
                            (device_serial, customer_name),
                        )

                        existing = cursor.fetchone()

                        if existing:
                            # Preserve the blacklist decision while refreshing metadata.
                            cursor.execute(
                                """
                                UPDATE blacklist
                                SET customer_channel = COALESCE(?, customer_channel),
                                    avatar_url = COALESCE(?, avatar_url),
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE id = ?
                            """,
                                (customer_channel, avatar_url, existing["id"]),
                            )
                            updated += 1
                        else:
                            # New record: insert with is_blacklisted=0 (default allow)
                            cursor.execute(
                                """
                                INSERT INTO blacklist (
                                    device_serial, customer_name, customer_channel,
                                    avatar_url, reason, is_blacklisted
                                )
                                VALUES (?, ?, ?, ?, ?, 0)
                            """,
                                (device_serial, customer_name, customer_channel, avatar_url, reason),
                            )
                            inserted += 1

                    except Exception as e:
                        logger.error(f"Failed to upsert user {user}: {e}")
                        failed += 1

                conn.commit()

                # Invalidate cache so checker reloads
                BlacklistChecker.invalidate_cache()

                logger.info(
                    f"Upsert scanned users for device {device_serial}: "
                    f"{inserted} inserted, {updated} updated, {failed} failed"
                )

                return {
                    "inserted": inserted,
                    "updated": updated,
                    "failed": failed,
                }

        except Exception as e:
            logger.error(f"Failed to upsert scanned users: {e}")
            return {
                "inserted": inserted,
                "updated": updated,
                "failed": failed,
            }

    def get_whitelist(self, device_serial: str) -> set[tuple[str, str | None]]:
        """
        Get whitelisted users (is_blacklisted=0) for a device.

        Used in Phase 2 of full sync to get users that should be synced.

        Args:
            device_serial: Device serial number

        Returns:
            Set of (customer_name, customer_channel) tuples
        """
        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT customer_name, customer_channel
                    FROM blacklist
                    WHERE device_serial = ? AND is_blacklisted = 0
                """,
                    (device_serial,),
                )

                whitelist = set()
                for row in cursor.fetchall():
                    whitelist.add((row["customer_name"], row["customer_channel"]))

                return whitelist

        except Exception as e:
            logger.error(f"Failed to get whitelist for device {device_serial}: {e}")
            return set()

    def get_whitelist_names(self, device_serial: str) -> set[str]:
        """
        Get whitelisted customer names for a device using name-only identity.

        Runtime blacklist checks use `customer_name` as the business identity.
        This helper keeps sync filtering aligned even if historical rows contain
        channel variants for the same customer.
        """
        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT customer_name
                    FROM blacklist
                    WHERE device_serial = ?
                    GROUP BY customer_name
                    HAVING MAX(CASE WHEN is_blacklisted = 1 THEN 1 ELSE 0 END) = 0
                       AND SUM(CASE WHEN is_blacklisted = 0 THEN 1 ELSE 0 END) > 0
                """,
                    (device_serial,),
                )

                return {row["customer_name"] for row in cursor.fetchall()}

        except Exception as e:
            logger.error(f"Failed to get whitelist names for device {device_serial}: {e}")
            return set()

    def get_blacklist_reason(self, device_serial: str, customer_name: str) -> str | None:
        """Get the latest blacklist reason for a customer using name-only identity."""
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT reason
                    FROM blacklist
                    WHERE device_serial = ?
                      AND customer_name = ?
                      AND is_blacklisted = 1
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                """,
                    (device_serial, customer_name),
                )
                row = cursor.fetchone()
                return row["reason"] if row else None
        except Exception as e:
            logger.error(f"Failed to get blacklist reason for {customer_name} on {device_serial}: {e}")
            return None

    def is_blacklisted_by_name(self, device_serial: str, customer_name: str) -> bool:
        """
        Check if a customer is currently blacklisted using name-only identity.

        Args:
            device_serial: Device serial number
            customer_name: Customer name

        Returns:
            True if blacklisted, False otherwise
        """
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT 1 FROM blacklist
                    WHERE device_serial = ?
                      AND customer_name = ?
                      AND is_blacklisted = 1
                    LIMIT 1
                """,
                    (device_serial, customer_name),
                )
                return cursor.fetchone() is not None
        except Exception as exc:
            logger.error("Failed to check blacklist for %s on %s: %s", customer_name, device_serial, exc)
            return False

    def add_to_blacklist(
        self,
        device_serial: str,
        customer_name: str,
        customer_channel: str | None = None,
        reason: str = "",
        deleted_by_user: bool = False,
        customer_db_id: int | None = None,
    ) -> bool:
        """
        Add a customer to the blacklist.

        Args:
            device_serial: Device serial number
            customer_name: Customer name
            customer_channel: Optional channel (like @WeChat)
            reason: Reason for blacklisting
            deleted_by_user: Whether the user deleted the kefu
            customer_db_id: Optional database ID of the customer

        Returns:
            True if successful, False otherwise
        """
        normalized_channel = _normalize_channel(customer_channel)
        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                # Name is unique per device in business logic; ignore channel in matching.
                cursor.execute(
                    """
                    SELECT id FROM blacklist
                    WHERE device_serial = ?
                        AND customer_name = ?
                """,
                    (device_serial, customer_name),
                )

                existing = cursor.fetchone()

                if existing:
                    # Update existing record
                    cursor.execute(
                        """
                        UPDATE blacklist
                        SET is_blacklisted = 1,
                            reason = ?,
                            deleted_by_user = ?,
                            customer_db_id = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """,
                        (reason, deleted_by_user, customer_db_id, existing["id"]),
                    )
                else:
                    # Insert new record
                    cursor.execute(
                        """
                        INSERT INTO blacklist (
                            device_serial, customer_name, customer_channel,
                            reason, is_blacklisted, deleted_by_user, customer_db_id
                        )
                        VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                        (device_serial, customer_name, normalized_channel, reason, deleted_by_user, customer_db_id),
                    )

                conn.commit()

                # Invalidate cache so checker reloads
                BlacklistChecker.invalidate_cache()

                logger.info(
                    f"Added {customer_name} to blacklist for device {device_serial} "
                    f"(reason: {reason}, deleted_by_user: {deleted_by_user})"
                )

                # Log to metrics
                try:
                    from wecom_automation.core.metrics_logger import get_metrics_logger

                    metrics = get_metrics_logger(device_serial)
                    metrics.log_blacklist_added(
                        customer_db_id=customer_db_id,
                        customer_name=customer_name,
                        channel=normalized_channel,
                        reason=reason or "Unknown",
                        deleted_by_user=deleted_by_user,
                    )
                except Exception as metrics_error:
                    logger.debug(f"Failed to log blacklist metrics: {metrics_error}")

                self._cancel_pending_followups_for_customer(
                    device_serial=device_serial,
                    customer_name=customer_name,
                    reason=f"User added to blacklist: {reason or 'manual'}",
                )

                return True

        except Exception as e:
            logger.error(f"Failed to add {customer_name} to blacklist: {e}")
            return False

    def remove_from_blacklist(
        self,
        device_serial: str,
        customer_name: str,
        customer_channel: str | None = None,
    ) -> bool:
        """
        Remove a user from the blacklist by setting is_blacklisted=0.

        Uses UPDATE instead of DELETE to preserve records for re-scan.

        Args:
            device_serial: Device serial number
            customer_name: Customer name
            customer_channel: Optional channel (like @WeChat)

        Returns:
            True if successful, False if not found or failed
        """
        normalized_channel = _normalize_channel(customer_channel)
        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    UPDATE blacklist
                    SET is_blacklisted = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE device_serial = ?
                        AND customer_name = ?
                        AND is_blacklisted = 1
                """,
                    (device_serial, customer_name),
                )

                if cursor.rowcount > 0:
                    conn.commit()

                    # Invalidate cache so checker reloads
                    BlacklistChecker.invalidate_cache()

                    logger.info(f"Removed from blacklist: {customer_name} ({normalized_channel}) on {device_serial}")
                    return True
                else:
                    logger.warning(
                        f"Not in blacklist or already removed: {customer_name} ({normalized_channel}) on {device_serial}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Failed to remove from blacklist: {e}")
            return False

    def ensure_user_in_blacklist_table(
        self,
        device_serial: str,
        customer_name: str,
        customer_channel: str | None = None,
        avatar_url: str | None = None,
    ) -> bool:
        """
        Ensure a user exists in the blacklist table (as whitelisted if new).

        If the user is not in the table, insert them with is_blacklisted=0.
        If they are already in the table, do nothing (keep existing status).

        Args:
            device_serial: Device serial number
            customer_name: Customer name
            customer_channel: Optional channel (like @WeChat)
            avatar_url: Optional avatar URL

        Returns:
            True if successful, False otherwise
        """
        if not device_serial or not customer_name:
            return False
        normalized_channel = _normalize_channel(customer_channel)

        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                # Check existence
                cursor.execute(
                    """
                    SELECT 1 FROM blacklist
                    WHERE device_serial = ? AND customer_name = ?
                """,
                    (device_serial, customer_name),
                )

                if cursor.fetchone():
                    return True  # Already exists

                # Insert as whitelisted (is_blacklisted=0)
                cursor.execute(
                    """
                    INSERT INTO blacklist (
                        device_serial, customer_name, customer_channel,
                        is_blacklisted, avatar_url, reason
                    )
                    VALUES (?, ?, ?, 0, ?, 'Auto-detected by FollowUp')
                """,
                    (device_serial, customer_name, normalized_channel, avatar_url),
                )
                conn.commit()

                logger.info(f"Auto-added user to blacklist table (allowed): {customer_name} on {device_serial}")
                return True

        except Exception as e:
            logger.error(f"Failed to ensure user in blacklist table: {e}")
            return False

    def copy_device_entries(
        self,
        source_device_serial: str,
        target_device_serial: str,
        *,
        include_allowed: bool = True,
        overwrite_existing: bool = True,
    ) -> dict[str, int]:
        """
        Copy blacklist rows from one device serial to another.

        This is primarily used when a physical Android device is replaced and
        the operator wants the new device to inherit the old device's blacklist
        decisions before or after the first sync.

        Notes:
        - Rows are copied by (customer_name, customer_channel) within the target
          device scope.
        - The copy only transfers portable blacklist state and metadata.

        Returns:
            Dict with copied_count, updated_count, skipped_count, total_source_entries
        """
        if not source_device_serial or not target_device_serial:
            raise ValueError("source_device_serial and target_device_serial are required")
        if source_device_serial == target_device_serial:
            raise ValueError("source_device_serial and target_device_serial must be different")

        copied_count = 0
        updated_count = 0
        skipped_count = 0

        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                query = """
                    SELECT
                        customer_name,
                        customer_channel,
                        reason,
                        deleted_by_user,
                        is_blacklisted,
                        avatar_url,
                        created_at,
                        updated_at
                    FROM blacklist
                    WHERE device_serial = ?
                """
                params: list[object] = [source_device_serial]
                if not include_allowed:
                    query += " AND is_blacklisted = 1"
                query += " ORDER BY created_at DESC, id DESC"

                cursor.execute(query, params)
                source_rows = cursor.fetchall()

                for row in source_rows:
                    normalized_channel = _normalize_channel(row["customer_channel"])
                    cursor.execute(
                        """
                        SELECT id, avatar_url
                        FROM blacklist
                        WHERE device_serial = ?
                          AND customer_name = ?
                          AND (
                              customer_channel = ?
                              OR (customer_channel IS NULL AND ? IS NULL)
                          )
                        """,
                        (target_device_serial, row["customer_name"], normalized_channel, normalized_channel),
                    )
                    existing = cursor.fetchone()

                    if existing:
                        if not overwrite_existing:
                            skipped_count += 1
                            continue

                        avatar_url = row["avatar_url"] or existing["avatar_url"]
                        cursor.execute(
                            """
                            UPDATE blacklist
                            SET reason = ?,
                                deleted_by_user = ?,
                                is_blacklisted = ?,
                                avatar_url = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                row["reason"],
                                row["deleted_by_user"],
                                row["is_blacklisted"],
                                avatar_url,
                                existing["id"],
                            ),
                        )
                        updated_count += 1
                        continue

                    cursor.execute(
                        """
                        INSERT INTO blacklist (
                            device_serial,
                            customer_name,
                            customer_channel,
                            reason,
                            deleted_by_user,
                            is_blacklisted,
                            avatar_url,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            target_device_serial,
                            row["customer_name"],
                            normalized_channel,
                            row["reason"],
                            row["deleted_by_user"],
                            row["is_blacklisted"],
                            row["avatar_url"],
                            row["created_at"],
                            row["updated_at"],
                        ),
                    )
                    copied_count += 1

                conn.commit()
                BlacklistChecker.invalidate_cache()

                logger.info(
                    "Copied blacklist entries from %s to %s: %s copied, %s updated, %s skipped",
                    source_device_serial,
                    target_device_serial,
                    copied_count,
                    updated_count,
                    skipped_count,
                )

                return {
                    "copied_count": copied_count,
                    "updated_count": updated_count,
                    "skipped_count": skipped_count,
                    "total_source_entries": len(source_rows),
                }

        except Exception as e:
            logger.error(
                "Failed to copy blacklist entries from %s to %s: %s",
                source_device_serial,
                target_device_serial,
                e,
            )
            raise

    def list_blacklist(self, device_serial: str | None = None) -> list[dict]:
        """
        Get blacklist entries (only is_blacklisted=1).

        Args:
            device_serial: Optional device serial to filter by

        Returns:
            List of blacklist entry dictionaries
        """
        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                if device_serial:
                    cursor.execute(
                        """
                        SELECT id, device_serial, customer_name, customer_channel,
                               reason, deleted_by_user, created_at, updated_at
                        FROM blacklist
                        WHERE device_serial = ? AND is_blacklisted = 1
                        ORDER BY created_at DESC
                    """,
                        (device_serial,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, device_serial, customer_name, customer_channel,
                               reason, deleted_by_user, created_at, updated_at
                        FROM blacklist
                        WHERE is_blacklisted = 1
                        ORDER BY created_at DESC
                    """
                    )

                results = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "id": row["id"],
                            "device_serial": row["device_serial"],
                            "customer_name": row["customer_name"],
                            "customer_channel": row["customer_channel"],
                            "reason": row["reason"],
                            "deleted_by_user": bool(row["deleted_by_user"]),
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                        }
                    )

                return results

        except Exception as e:
            logger.error(f"Failed to list blacklist: {e}")
            return []

    def list_blacklist_with_status(self, device_serial: str | None = None) -> list[dict]:
        """
        Get all blacklist entries including is_blacklisted status and avatar_url.

        Args:
            device_serial: Optional device serial to filter by

        Returns:
            List of all blacklist entry dictionaries with status
        """
        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                if device_serial:
                    cursor.execute(
                        """
                        SELECT id, device_serial, customer_name, customer_channel,
                               reason, deleted_by_user, is_blacklisted, avatar_url,
                               created_at, updated_at
                        FROM blacklist
                        WHERE device_serial = ?
                        ORDER BY created_at DESC
                    """,
                        (device_serial,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, device_serial, customer_name, customer_channel,
                               reason, deleted_by_user, is_blacklisted, avatar_url,
                               created_at, updated_at
                        FROM blacklist
                        ORDER BY created_at DESC
                    """
                    )

                results = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "id": row["id"],
                            "device_serial": row["device_serial"],
                            "customer_name": row["customer_name"],
                            "customer_channel": row["customer_channel"],
                            "reason": row["reason"],
                            "deleted_by_user": bool(row["deleted_by_user"]),
                            "is_blacklisted": bool(row["is_blacklisted"]),
                            "avatar_url": row["avatar_url"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                        }
                    )

                return results

        except Exception as e:
            logger.error(f"Failed to list blacklist with status: {e}")
            return []

    def list_customers_with_status(
        self,
        device_serial: str,
        search: str | None = None,
        filter_status: str = "all",
    ) -> list[dict]:
        """
        Get all customers for a device with their blacklist status.

        Joins with customers table to show message counts and last message date.

        Args:
            device_serial: Device serial number
            search: Optional search term for customer name
            filter_status: Filter by status (all/blacklisted/not_blacklisted)

        Returns:
            List of customer dictionaries with blacklist status
        """
        try:
            customer_db_path = self._get_customer_db_path(device_serial)
            blacklist_status_map = self._load_blacklist_status_map(device_serial)

            conn = sqlite3.connect(customer_db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()

                query = """
                    SELECT
                        c.name as customer_name,
                        c.channel as customer_channel,
                        c.last_message_preview,
                        c.last_message_date,
                        COUNT(m.id) as message_count
                    FROM customers c
                    LEFT JOIN messages m ON c.id = m.customer_id
                    WHERE c.kefu_id IN (
                        SELECT kd.kefu_id FROM kefu_devices kd
                        JOIN devices d ON d.id = kd.device_id
                        WHERE d.serial = ?
                    )
                """

                params = [device_serial]

                if search:
                    query += " AND c.name LIKE ?"
                    params.append(f"%{search}%")

                query += " GROUP BY c.id ORDER BY c.last_message_date DESC"
                cursor.execute(query, params)

                results = []
                for row in cursor.fetchall():
                    blacklist_entry = blacklist_status_map.get(row["customer_name"])
                    is_blacklisted = blacklist_entry is not None

                    if filter_status == "blacklisted" and not is_blacklisted:
                        continue
                    if filter_status == "not_blacklisted" and is_blacklisted:
                        continue

                    results.append(
                        {
                            "customer_name": row["customer_name"],
                            "customer_channel": row["customer_channel"],
                            "is_blacklisted": is_blacklisted,
                            "blacklist_reason": blacklist_entry["reason"] if blacklist_entry else None,
                            "deleted_by_user": bool(blacklist_entry["deleted_by_user"]) if blacklist_entry else False,
                            "last_message_at": row["last_message_date"],
                            "message_count": row["message_count"],
                        }
                    )

                return results
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Failed to list customers with status: {e}")
            return []

    def update_status(self, entry_id: int, is_blacklisted: bool) -> bool:
        """
        Update blacklist status for the full customer identity behind an entry ID.

        Args:
            entry_id: Blacklist entry ID
            is_blacklisted: New blacklist status

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT device_serial, customer_name
                    FROM blacklist
                    WHERE id = ?
                """,
                    (entry_id,),
                )
                target = cursor.fetchone()
                if not target:
                    logger.warning(f"Blacklist entry not found: {entry_id}")
                    return False

                cursor.execute(
                    """
                    UPDATE blacklist
                    SET is_blacklisted = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE device_serial = ?
                      AND customer_name = ?
                """,
                    (1 if is_blacklisted else 0, target["device_serial"], target["customer_name"]),
                )

                conn.commit()

                # Invalidate cache
                BlacklistChecker.invalidate_cache()

                logger.info(
                    "Updated blacklist status for %s/%s to %s via entry %s",
                    target["device_serial"],
                    target["customer_name"],
                    is_blacklisted,
                    entry_id,
                )

                if is_blacklisted:
                    self._cancel_pending_followups_for_customer(
                        device_serial=target["device_serial"],
                        customer_name=target["customer_name"],
                        reason="User blacklisted via update_status",
                    )
                return cursor.rowcount > 0

        except Exception as e:
            logger.error(f"Failed to update blacklist status: {e}")
            return False

    def batch_update_status(self, entry_ids: list[int], is_blacklisted: bool) -> dict[str, int]:
        """
        Batch update is_blacklisted status for multiple entries.

        Args:
            entry_ids: List of blacklist entry IDs
            is_blacklisted: New blacklist status

        Returns:
            Dict with success_count and failed_count
        """
        success_count = 0
        failed_count = 0

        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                identities: set[tuple[str, str]] = set()

                for entry_id in entry_ids:
                    try:
                        cursor.execute(
                            """
                            SELECT device_serial, customer_name
                            FROM blacklist
                            WHERE id = ?
                        """,
                            (entry_id,),
                        )
                        target = cursor.fetchone()
                        if not target:
                            failed_count += 1
                            continue
                        identities.add((target["device_serial"], target["customer_name"]))
                    except Exception as e:
                        logger.error(f"Failed to update entry {entry_id}: {e}")
                        failed_count += 1

                for device_serial, customer_name in identities:
                    try:
                        cursor.execute(
                            """
                            UPDATE blacklist
                            SET is_blacklisted = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE device_serial = ?
                              AND customer_name = ?
                        """,
                            (1 if is_blacklisted else 0, device_serial, customer_name),
                        )
                        success_count += cursor.rowcount
                    except Exception as e:
                        logger.error(f"Failed to update blacklist identity {device_serial}/{customer_name}: {e}")
                        failed_count += 1

                conn.commit()

                # Invalidate cache
                BlacklistChecker.invalidate_cache()

                logger.info(f"Batch update blacklist status: {success_count} succeeded, {failed_count} failed")

                if is_blacklisted:
                    for device_serial, customer_name in identities:
                        self._cancel_pending_followups_for_customer(
                            device_serial=device_serial,
                            customer_name=customer_name,
                            reason="User blacklisted via batch_update_status",
                        )

                return {
                    "success_count": success_count,
                    "failed_count": failed_count,
                }

        except Exception as e:
            logger.error(f"Failed to batch update blacklist status: {e}")
            return {
                "success_count": success_count,
                "failed_count": failed_count,
            }
