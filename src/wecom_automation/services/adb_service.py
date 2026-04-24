"""
ADB Service - Low-level device interaction layer.

This service wraps the DroidRun AdbTools to provide:
- Connection management
- Screen interaction (tap, swipe)
- UI tree retrieval
- Screenshot capture
- Optimized caching for DroidRun overlay feature
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from droidrun import AdbTools

from wecom_automation.core.config import Config
from wecom_automation.core.exceptions import (
    DeviceConnectionError,
    WeComAutomationError,
)
from wecom_automation.core.logging import get_logger, log_operation
from wecom_automation.core.models import DeviceInfo
from wecom_automation.core.performance import runtime_metrics
from wecom_automation.services.device_service import DeviceDiscoveryService


@dataclass
class UIStateCache:
    """
    Cache for DroidRun UI state with TTL-based invalidation.

    This cache stores all data from get_state() including:
    - formatted_text: Human-readable UI text
    - focused_text: Currently focused element
    - raw_tree: Full UI accessibility tree
    - clickable_elements: Pre-processed flat list of clickable elements
    - tree_hash: Hash for change detection
    - text_index: O(1) lookup by text

    The cache is automatically invalidated after UI-modifying operations
    like tap(), swipe(), input_text(), etc.
    """

    formatted_text: str = ""
    focused_text: str = ""
    raw_tree: Any = None
    clickable_elements: list[dict[str, Any]] = field(default_factory=list)
    tree_hash: str = ""
    text_index: dict[str, dict] = field(default_factory=dict)
    timestamp: float = 0.0

    def is_valid(self, ttl_seconds: float = 0.5) -> bool:
        """
        Check if cache is still fresh (within TTL).

        Args:
            ttl_seconds: Time-to-live in seconds (default 0.5s)

        Returns:
            True if cache is valid, False if expired or never set
        """
        if self.timestamp == 0.0:
            return False
        return (time.time() - self.timestamp) < ttl_seconds

    def invalidate(self) -> None:
        """Force cache to be refreshed on next query."""
        self.timestamp = 0.0


class ADBService:
    """
    Service for low-level Android device interaction.

    This class wraps DroidRun's AdbTools to provide a cleaner interface
    with proper error handling, logging, and retry logic.

    Usage:
        service = ADBService(config)
        await service.start_app("com.tencent.wework")
        tree = await service.get_ui_tree()
    """

    def __init__(self, config: Config):
        """
        Initialize the ADB service.

        Args:
            config: Application configuration
        """
        self.config = config
        self.logger = get_logger("wecom_automation.adb")
        self._adb: AdbTools | None = None
        self._connected = False
        self._cache = UIStateCache()
        self._last_tree_hash: str = ""

        # Swipe statistics for log aggregation
        self._swipe_stats = {
            "phase1_scroll_up": {
                "count": 0,
                "start_x": 540,
                "start_y": 350,
                "end_x": 540,
                "end_y": 1300,
                "duration_ms": 150,
            },
            "phase2_scroll_down": {
                "count": 0,
                "start_x": 540,
                "start_y": 1100,
                "end_x": 540,
                "end_y": 500,
                "duration_ms": 300,
            },
            "user_list_scroll": {
                "count": 0,
                "start_x": 540,
                "start_y": 1200,
                "end_x": 540,
                "end_y": 600,
                "duration_ms": 300,
            },
            "scroll_to_top": {
                "count": 0,
                "start_x": 540,
                "start_y": 400,
                "end_x": 540,
                "end_y": 1000,
                "duration_ms": 300,
            },
            "other_swipe": {"count": 0, "params": []},  # For non-standard swipes
        }

    def _trace_context(self, step: str, **fields: Any) -> str:
        """Build a compact, grep-friendly trace context for ADB bottleneck debugging."""
        serial = self.config.device_serial or "unknown"
        parts = [
            "[ADB_TRACE]",
            f"serial={serial}",
            f"pid={os.getpid()}",
            f"step={step}",
        ]
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        return " ".join(parts)

    def _trace_start(self, step: str, **fields: Any) -> float:
        self.logger.info(self._trace_context(step, event="start", **fields))
        return time.perf_counter()

    def _trace_end(self, step: str, started: float, **fields: Any) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        self.logger.info(
            self._trace_context(
                step,
                event="end",
                duration_ms=f"{duration_ms:.1f}",
                **fields,
            )
        )

    @property
    def adb(self) -> AdbTools:
        """Get the AdbTools instance, initializing if needed."""
        if self._adb is None:
            self._adb = AdbTools(
                serial=self.config.device_serial,
                use_tcp=self.config.use_tcp,
                remote_tcp_port=self.config.droidrun_port,  # Use configured port for multi-device support
            )
        return self._adb

    @property
    def is_connected(self) -> bool:
        """Check if connected to a device."""
        return self._connected

    def invalidate_cache(self) -> None:
        """Invalidate the UI state cache (called after UI-modifying operations)."""
        self._cache.invalidate()

    def hash_ui_tree(self, tree: Any) -> str:
        """
        Generate a deterministic hash for UI tree comparisons.

        This is useful for detecting whether the UI has changed between
        scroll operations or other actions.

        Args:
            tree: The UI tree to hash

        Returns:
            A string hash of the tree
        """
        try:
            serialized = json.dumps(tree, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized = str(tree)
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()

    def is_tree_unchanged(self) -> bool:
        """
        Check if UI tree matches previous hash (skip re-parsing optimization).

        This is useful for detecting when scrolling has reached the end
        or when the UI hasn't changed after an action.

        Returns:
            True if tree hash matches previous hash, False otherwise
        """
        if not self._last_tree_hash:
            return False
        return self._cache.tree_hash == self._last_tree_hash

    def _build_text_index(self) -> dict[str, dict]:
        """
        Build text index from clickable elements for O(1) lookup.

        Maps lowercased text to clickable element. First element wins
        for duplicate text.

        Returns:
            Dictionary mapping lowercase text to element
        """
        index: dict[str, dict] = {}
        for element in self._cache.clickable_elements:
            text = (element.get("text") or "").strip().lower()
            if text and text not in index:
                index[text] = element
        return index

    def find_by_text_indexed(self, text: str) -> dict[str, Any] | None:
        """
        O(1) lookup of element by text using text index.

        This is much faster than searching the entire list for
        frequently accessed elements.

        Args:
            text: Text to search for (case insensitive)

        Returns:
            Element dictionary if found, None otherwise
        """
        return self._cache.text_index.get(text.lower())

    def get_element_by_index(self, index: int) -> dict[str, Any] | None:
        """
        Get a clickable element directly by its index.

        This is useful when you know the index from the overlay numbers.
        Direct O(1) array access.

        Args:
            index: Element index from clickable_elements_cache

        Returns:
            Element dictionary if found, None otherwise
        """
        elements = self._cache.clickable_elements
        if 0 <= index < len(elements):
            return elements[index]
        self.logger.warning(f"Index {index} out of range (0-{len(elements) - 1})")
        return None

    def _matches_text(self, text: str, patterns: tuple[str, ...], exact: bool = False) -> bool:
        """
        Check if text matches any of the patterns.

        Args:
            text: Text to check
            patterns: Tuple of patterns to match against
            exact: If True, require exact match; if False, partial match

        Returns:
            True if text matches any pattern
        """
        text_lower = text.lower()
        for pattern in patterns:
            pattern_lower = pattern.lower()
            if exact:
                if text_lower == pattern_lower:
                    return True
            else:
                if pattern_lower in text_lower:
                    return True
        return False

    async def find_clickable_by_text(
        self,
        patterns: tuple[str, ...],
        exact: bool = False,
    ) -> dict[str, Any] | None:
        """
        Find a clickable element by text patterns.

        Optimized for flat clickable_elements_cache (no recursion).

        Args:
            patterns: Tuple of text patterns to match
            exact: If True, require exact match; if False, partial match

        Returns:
            Element dictionary if found, None otherwise
        """
        await self.refresh_state()
        for element in self._cache.clickable_elements:
            text = element.get("text", "")
            if text and self._matches_text(text, patterns, exact):
                self.logger.debug(f"Found clickable element by text: '{text}'")
                return element
        return None

    async def find_clickable_by_resource_id(
        self,
        patterns: tuple[str, ...],
    ) -> dict[str, Any] | None:
        """
        Find a clickable element by resource ID patterns.

        Optimized for flat clickable_elements_cache (no recursion).

        Args:
            patterns: Tuple of resource ID patterns to match

        Returns:
            Element dictionary if found, None otherwise
        """
        await self.refresh_state()
        for element in self._cache.clickable_elements:
            rid = (element.get("resourceId") or "").lower()
            for pattern in patterns:
                if pattern.lower() in rid:
                    self.logger.debug(f"Found clickable element by resource ID: '{rid}'")
                    return element
        return None

    async def tap_by_index(self, index: int, refresh_first: bool = True) -> str:
        """
        Refresh state and tap element by index in one call.

        This follows DroidRun's best practice of always calling get_state()
        before tap_by_index() to ensure the element cache is current.

        Args:
            index: Element index from clickable_elements_cache
            refresh_first: If True (default), refresh state before tapping

        Returns:
            Result message from the tap operation
        """
        if refresh_first:
            await self.refresh_state(force=True)

        result = await self.tap(index)
        return result

    async def tap_element(self, element: dict[str, Any]) -> str:
        """
        Tap using an element dictionary.

        Args:
            element: Element dictionary with 'index' key

        Returns:
            Result message from the tap operation

        Raises:
            WeComAutomationError: If element has no index
        """
        index = element.get("index")
        if index is None:
            raise WeComAutomationError(
                "Element has no index",
                context={"element": str(element)[:100]},
            )

        self.logger.debug(f"Tapping element: {element.get('text', 'unknown')}")
        result = await self.tap(index)
        return result

    def get_elements_by_type(self, class_name_contains: str) -> list[dict[str, Any]]:
        """
        Get elements filtered by class name.

        Args:
            class_name_contains: Substring to match in className (case insensitive)

        Returns:
            List of matching elements
        """
        pattern = class_name_contains.lower()
        return [
            element for element in self._cache.clickable_elements if pattern in (element.get("className") or "").lower()
        ]

    def get_buttons(self) -> list[dict[str, Any]]:
        """
        Get all button elements (Button, ImageButton).

        Returns:
            List of button elements
        """
        return self.get_elements_by_type("Button")

    def get_text_fields(self) -> list[dict[str, Any]]:
        """
        Get all text input field elements (EditText).

        Returns:
            List of text field elements
        """
        return self.get_elements_by_type("EditText")

    def get_image_views(self) -> list[dict[str, Any]]:
        """
        Get all image view elements (ImageView).

        Returns:
            List of image view elements
        """
        return self.get_elements_by_type("ImageView")

    @property
    def last_formatted_text(self) -> str:
        """
        Get the formatted text from the last get_state() call.

        This is useful for debugging and understanding the current UI state.

        Returns:
            Formatted text string, or empty string if not available
        """
        return self._cache.formatted_text

    @property
    def last_focused_text(self) -> str:
        """
        Get the focused element text from the last get_state() call.

        Returns:
            Focused text string, or empty string if not available
        """
        return self._cache.focused_text

    def log_ui_summary(self, max_elements: int = 20) -> None:
        """
        Log a comprehensive UI state summary for debugging.

        Args:
            max_elements: Maximum number of clickable elements to log
        """
        self.logger.info("=" * 60)
        self.logger.info("UI STATE SUMMARY")
        self.logger.info("=" * 60)

        # Log formatted text (first few lines)
        if self._cache.formatted_text:
            lines = self._cache.formatted_text.split("\n")[:10]
            self.logger.info("Formatted text (first 10 lines):")
            for line in lines:
                self.logger.info(f"  {line}")
        else:
            self.logger.info("Formatted text: (none)")

        # Log focused text
        if self._cache.focused_text:
            self.logger.info(f"Focused: {self._cache.focused_text}")
        else:
            self.logger.info("Focused: (none)")

        # Log clickable elements
        total = len(self._cache.clickable_elements)
        self.logger.info(f"\nClickable elements ({total} total):")

        for element in self._cache.clickable_elements[:max_elements]:
            index = element.get("index", "?")
            text = element.get("text", "")
            class_name = element.get("className", "unknown").split(".")[-1]
            self.logger.info(f"  [{index:>3}] {class_name}: '{text}'")

        if total > max_elements:
            self.logger.info(f"  ... and {total - max_elements} more")

        self.logger.info("=" * 60)

    async def _refresh_ui_state(self) -> None:
        """
        Internal method to refresh UI state from device.

        Calls get_state() once and populates cache with both
        raw_tree_cache and clickable_elements_cache.
        Also updates tree hash for change detection.
        """
        self.logger.debug("Refreshing UI state from device...")
        started = self._trace_start("get_state", caller="refresh_ui_state")
        try:
            await self.adb.get_state()
            runtime_metrics.record_adb_call("get_state", (time.perf_counter() - started) * 1000)
        except Exception as e:
            self._trace_end("get_state", started, caller="refresh_ui_state", status="error", error=type(e).__name__)
            raise

        # Save previous hash before updating
        self._last_tree_hash = self._cache.tree_hash

        self._cache.raw_tree = getattr(self.adb, "raw_tree_cache", None)
        self._cache.clickable_elements = getattr(self.adb, "clickable_elements_cache", [])
        self._cache.tree_hash = self.hash_ui_tree(self._cache.raw_tree)
        self._cache.text_index = self._build_text_index()
        self._cache.timestamp = time.time()

        self.logger.debug(
            f"UI state refreshed: tree={'present' if self._cache.raw_tree else 'empty'}, "
            f"{len(self._cache.clickable_elements)} clickable elements, "
            f"{len(self._cache.text_index)} indexed texts"
        )
        self._trace_end(
            "get_state",
            started,
            caller="refresh_ui_state",
            status="ok",
            tree="present" if self._cache.raw_tree else "empty",
            clickables=len(self._cache.clickable_elements),
        )

    async def get_ui_state(self, force: bool = False) -> tuple[Any | None, list[dict[str, Any]]]:
        """
        Get both UI tree and clickable elements in a single get_state() call.

        This is more efficient than calling get_ui_tree() and get_clickable_elements()
        separately, as it avoids redundant get_state() calls.

        Args:
            force: If True, bypass cache and fetch fresh state

        Returns:
            Tuple of (ui_tree, clickable_elements)
        """
        if not force and self._cache.is_valid():
            self.logger.debug("Using cached UI state")
            runtime_metrics.record_adb_call("get_state", 0.0, cached=True)
            return self._cache.raw_tree, self._cache.clickable_elements

        await self._refresh_ui_state()
        return self._cache.raw_tree, self._cache.clickable_elements

    async def refresh_state(self, force: bool = False) -> UIStateCache:
        """
        Refresh UI state and return the cache object.

        Central method for refreshing UI state with caching.

        Args:
            force: If True, bypass cache and fetch fresh state

        Returns:
            The UIStateCache object with current state
        """
        if not force and self._cache.is_valid():
            self.logger.debug("Using cached UI state")
            runtime_metrics.record_adb_call("get_state", 0.0, cached=True)
            return self._cache

        await self._refresh_ui_state()
        return self._cache

    async def connect(self) -> None:
        """
        Establish connection to the device.

        Raises:
            DeviceConnectionError: If connection fails
        """
        self.logger.info("Connecting to device...")
        try:
            # AdbTools initializes connection on first use
            # We verify by getting the UI state
            started = self._trace_start("get_state", caller="connect")
            await self.adb.get_state()
            runtime_metrics.record_adb_call("connect_get_state", (time.perf_counter() - started) * 1000)
            self._trace_end("get_state", started, caller="connect", status="ok")
            self._connected = True
            self.logger.info("Connected to device successfully")
        except Exception as e:
            if "started" in locals():
                self._trace_end("get_state", started, caller="connect", status="error", error=type(e).__name__)
            self._connected = False
            raise DeviceConnectionError(
                "Failed to connect to device",
                serial=self.config.device_serial,
                original_error=e,
            ) from e

    async def start_app(self, package_name: str) -> None:
        """
        Launch an application by package name.

        Args:
            package_name: Android package name (e.g., "com.tencent.wework")

        Raises:
            WeComAutomationError: If app launch fails
        """
        with log_operation(self.logger, "start_app", package=package_name):
            try:
                started = self._trace_start("start_app", package=package_name)
                await self.adb.start_app(package_name)
                runtime_metrics.record_adb_call("start_app", (time.perf_counter() - started) * 1000)
                self._trace_end("start_app", started, package=package_name, status="ok")
                self.invalidate_cache()  # UI changed after app launch
                self.logger.info(f"App launched: {package_name}")
            except Exception as e:
                if "started" in locals():
                    self._trace_end("start_app", started, package=package_name, status="error", error=type(e).__name__)
                raise WeComAutomationError(
                    f"Failed to start app: {package_name}",
                    original_error=e,
                ) from e

    async def get_ui_tree(self, refresh: bool = True) -> Any | None:
        """
        Get the current UI accessibility tree.

        Args:
            refresh: If True (default), always fetch fresh state.
                    If False, use cache when valid.

        Returns:
            The raw UI tree structure, or None if retrieval fails
        """
        self.logger.debug("Fetching UI tree...")
        try:
            # Use cache if valid and refresh not requested
            if not refresh and self._cache.is_valid():
                self.logger.debug("Using cached UI tree")
                runtime_metrics.record_adb_call("get_ui_tree", 0.0, cached=True)
                return self._cache.raw_tree

            await self._refresh_ui_state()

            if self._cache.raw_tree:
                self.logger.debug("UI tree retrieved successfully")
            else:
                self.logger.warning("UI tree is empty")
            return self._cache.raw_tree
        except Exception as e:
            self.logger.error(f"Failed to get UI tree: {e}")
            return None

    async def get_clickable_elements(self, refresh: bool = True) -> list[dict[str, Any]]:
        """
        Get all clickable UI elements.

        Args:
            refresh: If True (default), always fetch fresh state.
                    If False, use cache when valid.

        Returns:
            List of clickable element dictionaries
        """
        # Use cache if valid and refresh not requested
        if not refresh and self._cache.is_valid():
            self.logger.debug("Using cached clickable elements")
            return self._cache.clickable_elements

        await self._refresh_ui_state()
        self.logger.debug(f"Found {len(self._cache.clickable_elements)} clickable elements")
        return self._cache.clickable_elements

    async def tap(self, index: int) -> str:
        """
        Tap on a UI element by its index.

        Args:
            index: Element index from clickable_elements_cache

        Returns:
            Result message from the tap operation
        """
        self.logger.debug(f"Tapping element at index {index}")
        try:
            started = time.perf_counter()
            result = await self.adb.tap(index)
            runtime_metrics.record_adb_call("tap", (time.perf_counter() - started) * 1000)
            self.invalidate_cache()  # UI changed after tap
            self.logger.debug(f"Tap result: {result}")
            return result
        except Exception as e:
            self.logger.error(f"Tap failed: {e}")
            raise WeComAutomationError(
                f"Failed to tap element at index {index}",
                original_error=e,
            ) from e

    async def tap_coordinates(self, x: int, y: int) -> None:
        """
        Tap at specific screen coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
        """
        self.logger.debug(f"Tapping at coordinates ({x}, {y})")
        try:
            started = time.perf_counter()
            await self.adb.tap_by_coordinates(x, y)
            runtime_metrics.record_adb_call("tap_coordinates", (time.perf_counter() - started) * 1000)
            self.invalidate_cache()  # UI changed after tap
        except Exception as e:
            self.logger.error(f"Coordinate tap failed: {e}")
            raise WeComAutomationError(
                f"Failed to tap at coordinates ({x}, {y})",
                original_error=e,
            ) from e

    async def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int = 300,
    ) -> None:
        """
        Perform a swipe gesture.

        Args:
            start_x: Starting X coordinate
            start_y: Starting Y coordinate
            end_x: Ending X coordinate
            end_y: Ending Y coordinate
            duration_ms: Duration of the swipe in milliseconds
        """
        # Count swipe operations for log aggregation instead of logging each one
        self._count_swipe(start_x, start_y, end_x, end_y, duration_ms)

        try:
            started = self._trace_start(
                "swipe",
                start=f"{start_x},{start_y}",
                end=f"{end_x},{end_y}",
                requested_duration_ms=duration_ms,
            )
            await self.adb.swipe(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                duration_ms=duration_ms,
            )
            runtime_metrics.record_adb_call("swipe", (time.perf_counter() - started) * 1000)
            self._trace_end(
                "swipe",
                started,
                start=f"{start_x},{start_y}",
                end=f"{end_x},{end_y}",
                requested_duration_ms=duration_ms,
                status="ok",
            )
            self.invalidate_cache()  # UI changed after swipe
        except Exception as e:
            if "started" in locals():
                self._trace_end(
                    "swipe",
                    started,
                    start=f"{start_x},{start_y}",
                    end=f"{end_x},{end_y}",
                    requested_duration_ms=duration_ms,
                    status="error",
                    error=type(e).__name__,
                )
            self.logger.error(f"Swipe failed: {e}")
            raise WeComAutomationError(
                "Swipe operation failed",
                context={
                    "start": f"({start_x}, {start_y})",
                    "end": f"({end_x}, {end_y})",
                },
                original_error=e,
            ) from e

    def _count_swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int) -> None:
        """
        Count swipe operations for log aggregation.

        Identifies swipe patterns and increments appropriate counters.
        """
        # Phase 1: Fast scroll to top (540, 350 -> 540, 1300, 150ms)
        if start_x == 540 and start_y == 350 and end_x == 540 and end_y == 1300 and duration_ms == 150:
            self._swipe_stats["phase1_scroll_up"]["count"] += 1

        # Phase 2: Message extraction scroll down (540, 1100 -> 540, 500, 300ms)
        elif start_x == 540 and start_y == 1100 and end_x == 540 and end_y == 500 and duration_ms == 300:
            self._swipe_stats["phase2_scroll_down"]["count"] += 1

        # User list scroll (540, 1200 -> 540, 600, 300ms)
        elif start_x == 540 and start_y == 1200 and end_x == 540 and end_y == 600 and duration_ms == 300:
            self._swipe_stats["user_list_scroll"]["count"] += 1

        # Scroll to top (540, 400 -> 540, 1000, 300ms)
        elif start_x == 540 and start_y == 400 and end_x == 540 and end_y == 1000 and duration_ms == 300:
            self._swipe_stats["scroll_to_top"]["count"] += 1

        # Other swipes - store parameters for reporting
        else:
            self._swipe_stats["other_swipe"]["count"] += 1
            params_key = f"({start_x},{start_y}->{end_x},{end_y},{duration_ms}ms)"
            if params_key not in self._swipe_stats["other_swipe"]["params"]:
                self._swipe_stats["other_swipe"]["params"].append(params_key)

    def log_swipe_statistics(self, operation_name: str = "operation") -> None:
        """
        Log aggregated swipe statistics.

        Args:
            operation_name: Name of the operation for context
        """
        total_swipes = sum(
            stats["count"] for stats in self._swipe_stats.values() if isinstance(stats, dict) and "count" in stats
        )

        if total_swipes == 0:
            return

        stats_parts = []
        for key, stats in self._swipe_stats.items():
            if stats["count"] > 0:
                if key == "other_swipe":
                    if stats["count"] == 1 and stats["params"]:
                        stats_parts.append(f"1 other swipe ({stats['params'][0]})")
                    else:
                        stats_parts.append(f"{stats['count']} other swipes")
                elif key == "phase1_scroll_up":
                    stats_parts.append(
                        f"{stats['count']} Phase 1 scrolls ({stats['start_x']}, {stats['start_y']} -> {stats['end_x']}, {stats['end_y']}, {stats['duration_ms']}ms each)"
                    )
                elif key == "phase2_scroll_down":
                    stats_parts.append(
                        f"{stats['count']} Phase 2 scrolls ({stats['start_x']}, {stats['start_y']} -> {stats['end_x']}, {stats['end_y']}, {stats['duration_ms']}ms each)"
                    )
                elif key == "user_list_scroll":
                    stats_parts.append(
                        f"{stats['count']} user list scrolls ({stats['start_x']}, {stats['start_y']} -> {stats['end_x']}, {stats['end_y']}, {stats['duration_ms']}ms each)"
                    )
                elif key == "scroll_to_top":
                    stats_parts.append(
                        f"{stats['count']} scroll-to-top operations ({stats['start_x']}, {stats['start_y']} -> {stats['end_x']}, {stats['end_y']}, {stats['duration_ms']}ms each)"
                    )

        if stats_parts:
            self.logger.info(f"[Swipe Stats] {operation_name}: {', '.join(stats_parts)}")

        # Reset counters for next operation
        self._reset_swipe_stats()

    def _reset_swipe_stats(self) -> None:
        """Reset all swipe statistics counters."""
        for stats in self._swipe_stats.values():
            if isinstance(stats, dict):
                stats["count"] = 0
                if "params" in stats:
                    stats["params"] = []

    async def scroll_up(self) -> None:
        """Scroll up (reveal content above)."""
        config = self.config.scroll
        await self.swipe(
            start_x=config.start_x,
            start_y=config.scroll_up_start_y,
            end_x=config.start_x,
            end_y=config.scroll_up_end_y,
            duration_ms=config.swipe_duration_ms,
        )

    async def scroll_down(self, distance: int | None = None) -> None:
        """
        Scroll down (reveal content below).

        Args:
            distance: Optional custom scroll distance in pixels
        """
        config = self.config.scroll
        actual_distance = distance or config.scroll_distance
        await self.swipe(
            start_x=config.start_x,
            start_y=config.scroll_down_start_y,
            end_x=config.start_x,
            end_y=config.scroll_down_start_y - actual_distance,
            duration_ms=config.swipe_duration_ms,
        )

    async def scroll_to_top(self, scroll_count: int = 1000) -> None:
        """
        Scroll to the top of the current view.

        Args:
            scroll_count: Maximum number of scroll-up gestures to perform (safety limit).
                          Defaults to 1000 to ensure we can traverse long lists.
                          Stop condition is solely based on UI stability.
        """
        # Prioritize explicit argument, fallback to Config if argument is None (not default),
        # but since default is 1000, it effectively defaults to 1000.
        # We ignore config.scroll.scroll_to_top_attempts as it is likely too small (6).
        max_attempts = max(1, scroll_count)
        stable_threshold = self.config.scroll.scroll_to_top_stable_threshold

        self.logger.info(f"Scrolling to top (max_attempts={max_attempts}, stable_threshold={stable_threshold})...")
        overall_started = self._trace_start(
            "scroll_to_top",
            max_attempts=max_attempts,
            stable_threshold=stable_threshold,
        )

        previous_hash: str | None = None
        stable_count = 0

        try:
            for attempt in range(1, max_attempts + 1):
                self.logger.debug(f"Scroll-to-top {attempt}/{max_attempts}")
                attempt_started = self._trace_start("scroll_to_top.attempt", attempt=attempt, phase="swipe")
                await self.scroll_up()
                self._trace_end("scroll_to_top.attempt", attempt_started, attempt=attempt, phase="swipe", status="ok")

                sleep_started = self._trace_start(
                    "scroll_to_top.attempt",
                    attempt=attempt,
                    phase="stabilize_sleep",
                    sleep_seconds=self.config.timing.ui_stabilization_delay,
                )
                await asyncio.sleep(self.config.timing.ui_stabilization_delay)
                self._trace_end(
                    "scroll_to_top.attempt",
                    sleep_started,
                    attempt=attempt,
                    phase="stabilize_sleep",
                    status="ok",
                )

                tree_started = self._trace_start("scroll_to_top.attempt", attempt=attempt, phase="get_ui_tree")
                tree = await self.get_ui_tree()
                self._trace_end(
                    "scroll_to_top.attempt",
                    tree_started,
                    attempt=attempt,
                    phase="get_ui_tree",
                    status="ok",
                    tree="present" if tree else "empty",
                )
                if not tree:
                    continue

                tree_hash = self.hash_ui_tree(tree)
                if tree_hash == previous_hash:
                    stable_count += 1
                    self.logger.debug(f"UI unchanged for {stable_count} consecutive scrolls")
                    if stable_count >= stable_threshold:
                        self.logger.info("UI stable after consecutive scrolls - assuming top reached")
                        break
                else:
                    stable_count = 0
                    previous_hash = tree_hash
            else:
                self.logger.info("Reached maximum scroll-to-top attempts")
        except Exception as e:
            self._trace_end("scroll_to_top", overall_started, status="error", error=type(e).__name__)
            raise

        # Log scroll-to-top swipe statistics
        self.log_swipe_statistics("Scroll to top")

        self.logger.info("Scrolled to top")
        self._trace_end("scroll_to_top", overall_started, status="ok", stable_count=stable_count)

    async def take_screenshot(self) -> tuple[str, bytes]:
        """
        Take a screenshot of the current screen.

        Returns:
            Tuple of (format, image_bytes)

        Raises:
            WeComAutomationError: If screenshot fails
        """
        self.logger.debug("Taking screenshot...")
        try:
            started = time.perf_counter()
            result = await self.adb.take_screenshot()
            runtime_metrics.record_adb_call("take_screenshot", (time.perf_counter() - started) * 1000)
            self.logger.debug("Screenshot captured")
            return result
        except Exception as e:
            self.logger.error(f"Screenshot failed: {e}")
            raise WeComAutomationError(
                "Failed to take screenshot",
                original_error=e,
            ) from e

    async def wait(self, seconds: float) -> None:
        """
        Wait for a specified duration.

        Args:
            seconds: Time to wait in seconds
        """
        self.logger.debug(f"Waiting {seconds}s...")
        await asyncio.sleep(seconds)

    async def wait_for_ui_stable(self) -> None:
        """Wait for UI to stabilize after an action."""
        await self.wait(self.config.timing.ui_stabilization_delay)

    async def get_device_info(self, include_runtime_stats: bool = True) -> DeviceInfo:
        """
        Retrieve detailed information about the configured device.

        Args:
            include_runtime_stats: When True, fetch live metrics (battery, storage, etc.)

        Raises:
            DeviceConnectionError: If the device serial is missing or device is not found
        """
        serial = self.config.device_serial
        if not serial:
            raise DeviceConnectionError("device_serial is required to fetch device information")
        discovery = DeviceDiscoveryService(self.config)
        device = await discovery.get_device(
            serial,
            include_properties=True,
            include_runtime_stats=include_runtime_stats,
        )
        if not device:
            raise DeviceConnectionError(
                "Device not found or offline",
                serial=serial,
            )
        return device

    async def input_text(self, text: str) -> None:
        """
        Input text into the currently focused field.

        Args:
            text: Text to input
        """
        self.logger.debug(f"Inputting text: {text[:50]}...")
        try:
            # Use droidrun's input_text method
            started = time.perf_counter()
            await self.adb.input_text(text)
            runtime_metrics.record_adb_call("input_text", (time.perf_counter() - started) * 1000)
            self.invalidate_cache()  # UI changed after text input
        except Exception as e:
            self.logger.error(f"Input text failed: {e}")
            raise WeComAutomationError(
                "Failed to input text",
                original_error=e,
            ) from e

    async def press_enter(self) -> None:
        """Press the Enter key."""
        self.logger.debug("Pressing Enter key")
        try:
            # Use droidrun's press_key method with Enter keycode
            started = time.perf_counter()
            await self.adb.press_key(66)  # KEYCODE_ENTER
            runtime_metrics.record_adb_call("press_enter", (time.perf_counter() - started) * 1000)
            self.invalidate_cache()  # UI may change after Enter
        except Exception as e:
            self.logger.error(f"Press Enter failed: {e}")
            raise WeComAutomationError(
                "Failed to press Enter",
                original_error=e,
            ) from e

    async def press_back(self) -> None:
        """Press the Back button."""
        self.logger.debug("Pressing Back button")
        try:
            # Use droidrun's back method
            started = time.perf_counter()
            await self.adb.back()
            runtime_metrics.record_adb_call("press_back", (time.perf_counter() - started) * 1000)
            self.invalidate_cache()  # UI changed after back navigation
        except Exception as e:
            self.logger.error(f"Press Back failed: {e}")
            raise WeComAutomationError(
                "Failed to press Back",
                original_error=e,
            ) from e

    async def long_press(self, x: int, y: int, duration_ms: int = 1500) -> None:
        """
        Perform a long press at specific screen coordinates.

        A long press is implemented as a swipe from the same point to the same point
        with a longer duration (>500ms typically triggers long press).

        Args:
            x: X coordinate
            y: Y coordinate
            duration_ms: Duration of the press in milliseconds (default 1500ms)
        """
        self.logger.debug(f"Long pressing at ({x}, {y}) for {duration_ms}ms")
        try:
            # Long press = swipe from same point to same point with long duration
            await self.swipe(
                start_x=x,
                start_y=y,
                end_x=x,
                end_y=y,
                duration_ms=duration_ms,
            )
        except Exception as e:
            self.logger.error(f"Long press failed: {e}")
            raise WeComAutomationError(
                f"Failed to long press at ({x}, {y})",
                original_error=e,
            ) from e

    async def clear_text_field(self) -> None:
        """Clear the currently focused text field using Select All + Delete."""
        self.logger.debug("Clearing text field")
        try:
            # Ctrl+A to select all (keycode 29 with CTRL modifier doesn't work directly)
            # Instead, we'll use multiple delete keys or rely on the field being empty
            # For now, just press delete multiple times
            for _ in range(50):  # Clear up to 50 characters
                await self.adb.press_key(67)  # KEYCODE_DEL
            self.invalidate_cache()  # UI changed after clearing text
        except Exception as e:
            self.logger.error(f"Clear text field failed: {e}")
            raise WeComAutomationError(
                "Failed to clear text field",
                original_error=e,
            ) from e

    @staticmethod
    async def list_devices(
        include_properties: bool = True,
        include_runtime_stats: bool = False,
        verbose: bool = False,
    ) -> list[DeviceInfo]:
        """
        List all connected devices using DeviceDiscoveryService.
        """
        discovery = DeviceDiscoveryService()
        return await discovery.list_devices(
            include_properties=include_properties,
            include_runtime_stats=include_runtime_stats,
            verbose=verbose,
        )
