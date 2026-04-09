"""
Database retry utilities for handling concurrent access and transient errors.

This module provides:
- Automatic retry on database lock errors
- Exponential backoff strategy
- Configurable retry policies
"""

from __future__ import annotations

import functools
import sqlite3
import time
from typing import Any, Callable, TypeVar

from wecom_automation.core.logging import get_logger

logger = get_logger("wecom_automation.database.retry")

T = TypeVar("T")

# Default errors that trigger retry
DEFAULT_RETRY_ERRORS = (
    sqlite3.OperationalError,  # database is locked, disk I/O error
    sqlite3.DatabaseError,
)


def is_lock_error(error: Exception) -> bool:
    """Check if an error is a database lock error."""
    error_str = str(error).lower()
    return "locked" in error_str or "busy" in error_str


def retry_on_db_lock(
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 5.0,
    retry_on: tuple[type[Exception], ...] = DEFAULT_RETRY_ERRORS,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator that retries database operations on lock errors.

    Uses exponential backoff: delay = min(base_delay * (2 ** attempt), max_delay)

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 0.1)
        max_delay: Maximum delay in seconds (default: 5.0)
        retry_on: Tuple of exception types to retry on

    Returns:
        Decorated function with retry logic

    Example:
        @retry_on_db_lock(max_retries=5)
        def save_message(message):
            conn.execute("INSERT INTO messages ...")
            conn.commit()
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_error: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as e:
                    if not is_lock_error(e):
                        # Not a lock error, re-raise immediately
                        raise

                    last_error = e

                    if attempt < max_retries:
                        # Calculate delay with exponential backoff
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            f"Database lock detected, retrying in {delay:.3f}s "
                            f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        time.sleep(delay)
                    else:
                        # Max retries exceeded
                        logger.error(
                            f"Database operation failed after {max_retries + 1} attempts: {e}"
                        )

            # Should not reach here, but type checker needs it
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected state in retry decorator")

        return wrapper

    return decorator


def retry_on_db_lock_async(
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 5.0,
    retry_on: tuple[type[Exception], ...] = DEFAULT_RETRY_ERRORS,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Async version of retry_on_db_lock decorator.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 0.1)
        max_delay: Maximum delay in seconds (default: 5.0)
        retry_on: Tuple of exception types to retry on

    Returns:
        Decorated async function with retry logic

    Example:
        @retry_on_db_lock_async(max_retries=5)
        async def save_message(message):
            await conn.execute("INSERT INTO messages ...")
            await conn.commit()
    """
    import asyncio

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_error: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)  # type: ignore
                except retry_on as e:
                    if not is_lock_error(e):
                        raise

                    last_error = e

                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            f"Database lock detected, retrying in {delay:.3f}s "
                            f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Database operation failed after {max_retries + 1} attempts: {e}"
                        )

            if last_error:
                raise last_error
            raise RuntimeError("Unexpected state in async retry decorator")

        return wrapper  # type: ignore

    return decorator


class DatabaseRetryContext:
    """
    Context manager for database operations with retry logic.

    Example:
        with DatabaseRetryContext(max_retries=5) as retry:
            result = retry.execute(lambda: conn.execute("SELECT ..."))
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def execute(self, operation: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a database operation with retry logic."""
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return operation(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if not is_lock_error(e):
                    raise

                last_error = e

                if attempt < self.max_retries:
                    delay = min(self.base_delay * (2**attempt), self.max_delay)
                    logger.warning(
                        f"Database lock detected, retrying in {delay:.3f}s "
                        f"(attempt {attempt + 1}/{self.max_retries + 1}): {e}"
                    )
                    time.sleep(delay)

        if last_error:
            raise last_error
        raise RuntimeError("Unexpected state in retry context")

    def __enter__(self) -> "DatabaseRetryContext":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass
