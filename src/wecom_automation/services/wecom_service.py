"""
WeCom Service - High-level automation operations for WeCom app.

This service provides the main business logic for:
- Launching WeCom
- Navigating to Private Chats
- Extracting user details
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from wecom_automation.core.config import Config
from wecom_automation.core.exceptions import (
    NavigationError,
    UIElementNotFoundError,
)
from wecom_automation.core.logging import get_logger, log_operation
from wecom_automation.core.models import (
    ConversationExtractionResult,
    ConversationMessage,
    ExtractionResult,
    ImageInfo,
    KefuInfo,
    UserDetail,
)
from wecom_automation.services.adb_service import ADBService
from wecom_automation.services.group_invite import selectors as group_invite_selectors
from wecom_automation.services.timestamp_parser import TimestampParser
from wecom_automation.services.ui_parser import UIParserService, message_image_thumbnail_min_ok

# Try to import PIL for image operations
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# Helper to find the project's bundled ADB executable
def _get_project_adb_path() -> str:
    """Get the path to the bundled ADB executable in the project directory."""
    from wecom_automation.core.config import get_project_root

    project_root = get_project_root()

    # Try wecom-desktop/adb/adb.exe first
    adb_path = project_root / "wecom-desktop" / "adb" / "adb.exe"
    if adb_path.exists():
        return str(adb_path)

    # Try wecom-desktop/scrcpy/adb.exe as fallback
    adb_path = project_root / "wecom-desktop" / "scrcpy" / "adb.exe"
    if adb_path.exists():
        return str(adb_path)

    # Fall back to system adb
    return "adb"


# WeCom SILK cache basename: YYYY_MM_DD_HH_MM_SS_mmm.silk (local wall time)
_SILK_BASENAME_RE = re.compile(
    r"^(?P<y>\d{4})_(?P<m>\d{2})_(?P<d>\d{2})_(?P<H>\d{2})_(?P<M>\d{2})_(?P<S>\d{2})_(?P<ms>\d+)\.silk$"
)


def _parse_silk_basename_dt(remote_path: str) -> datetime | None:
    """Parse leading date+time from a remote .silk path basename; tz Asia/Shanghai."""
    name = remote_path.replace("\r", "").strip().split("/")[-1]
    m = _SILK_BASENAME_RE.match(name)
    if not m:
        return None
    y, mo, d = int(m["y"]), int(m["m"]), int(m["d"])
    H, M, S, ms = int(m["H"]), int(m["M"]), int(m["S"]), int(m["ms"])
    try:
        # last segment is milliseconds (3 digits in observed filenames)
        micro = min(ms * 1000, 999_999)
        return datetime(y, mo, d, H, M, S, micro, tzinfo=ZoneInfo("Asia/Shanghai"))
    except ValueError:
        return None


def _parse_silk_basename_date(remote_path: str) -> date | None:
    dt = _parse_silk_basename_dt(remote_path)
    return dt.date() if dt else None


def _silk_dt_sort_tuple(remote_path: str) -> tuple[int, int, int, int, int, int, int]:
    dt = _parse_silk_basename_dt(remote_path)
    if dt is None:
        return (0, 0, 0, 0, 0, 0, 0)
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)


def _voice_message_calendar_date(msg: ConversationMessage) -> date | None:
    """Resolve calendar date from message UI timestamp (None if missing / unparseable)."""
    raw = (msg.timestamp or "").strip()
    if not raw:
        return None
    from wecom_automation.services.timestamp_parser import TimestampParser

    p = TimestampParser()
    p.set_reference_time()
    dt = p.parse(raw)
    if dt is None:
        return None
    return dt.date()


def _expected_silk_byte_range_for_duration(duration_secs: int) -> tuple[int, int]:
    """
    Rough SILK file size range for a displayed voice length (seconds).
    UI may show 3\" for ~2.5s content; keep a band around ~2k bytes/s.
    """
    d = max(1, int(duration_secs))
    mid = d * 2000
    lo = max(512, int(mid * 0.50))
    hi = int(mid * 1.55)
    return lo, hi


def _silk_duration_score(file_size: int, duration_secs: int) -> int:
    mid = max(1, int(duration_secs)) * 2000
    return abs(file_size - mid)


def _remote_silk_file_size(adb_cmd: Callable[..., Any], remote_path: str) -> int | None:
    import subprocess

    r = subprocess.run(
        adb_cmd("shell", f"stat -c '%s' '{remote_path}' 2>/dev/null"),
        capture_output=True,
        text=True,
        timeout=5,
    )
    try:
        return int(r.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _select_silk_by_date_and_duration(
    adb_cmd: Callable[..., Any],
    paths: Sequence[str],
    *,
    target_date: date | None,
    duration_secs: int,
    captured_keys: set[str],
    logger,
) -> str | None:
    """
    Pick one .silk path: optional filter by YYYY-MM-DD from basename, then best byte-size vs UI duration.
    Tie-break: newest embedded datetime in filename (later recording wins when scores tie).
    """
    lo, hi = _expected_silk_byte_range_for_duration(duration_secs)

    def collect(use_date: date | None, require_band: bool) -> list[tuple[str, int, int, tuple[int, ...]]]:
        rows: list[tuple[str, int, int, tuple[int, ...]]] = []
        for silk_file in paths:
            if silk_file in captured_keys:
                continue
            dpart = _parse_silk_basename_date(silk_file)
            if use_date is not None and dpart != use_date:
                continue
            sz = _remote_silk_file_size(adb_cmd, silk_file)
            if sz is None:
                continue
            if require_band and not (lo <= sz <= hi):
                continue
            score = _silk_duration_score(sz, duration_secs)
            sk = _silk_dt_sort_tuple(silk_file)
            rows.append((silk_file, sz, score, sk))
        return rows

    rows = collect(target_date, True)
    if not rows and target_date is not None:
        logger.info(
            f"No SILK matched date={target_date} and duration~{duration_secs}s "
            f"(bytes in [{lo},{hi}]); retrying without date filter"
        )
        rows = collect(None, True)

    if not rows:
        logger.info(
            f"No SILK in byte band [{lo},{hi}]; relaxing band (still score by |size-mid|, prefer date={target_date})"
        )
        rows = collect(target_date, False)
        if not rows and target_date is not None:
            rows = collect(None, False)

    if not rows:
        logger.debug(f"No SILK candidates for ~{duration_secs}s (date filter={target_date})")
        return None

    rows.sort(key=lambda r: (r[2], -r[3][0], -r[3][1], -r[3][2], -r[3][3], -r[3][4], -r[3][5], -r[3][6]))
    best = rows[0]
    logger.info(
        f"Selected SILK (date={target_date or 'any'}, duration~{duration_secs}s): "
        f"{best[0]} size={best[1]} score={best[2]}"
    )
    return best[0]


class WeComService:
    """
    High-level service for WeCom automation.

    This service orchestrates the ADB and UI parser services to provide
    complete automation workflows for WeCom.

    Usage:
        config = Config()
        service = WeComService(config)

        # Full workflow
        await service.launch_wecom()
        await service.switch_to_private_chats()
        result = await service.extract_private_chat_users()
    """

    def __init__(self, config: Config | None = None):
        """
        Initialize the WeCom service.

        Args:
            config: Optional configuration (uses defaults if not provided)
        """
        self.config = config or Config()
        self.logger = get_logger("wecom_automation.wecom")
        self.adb = ADBService(self.config)
        self.ui_parser = UIParserService(self.config)
        self.timestamp_parser = TimestampParser(timezone=self.config.timezone)

        # Optional cancel checker - async function that raises exception if cancelled
        self._cancel_checker: Callable[[], Awaitable[None]] | None = None

        # Cached screen dimensions (lazily populated from UI tree root)
        self._screen_width: int = 1080
        self._screen_height: int = 2340

    @property
    def device_serial(self) -> str:
        """Get the device serial number."""
        return self.config.device_serial or "unknown"

    def _update_screen_dimensions(self, elements: list[dict]) -> None:
        """Detect and cache screen dimensions from the root element bounds."""
        if not elements:
            return
        root = elements[0] if elements else None
        if not root:
            return
        bounds = self._parse_element_bounds(root)
        if bounds:
            _, _, w, h = bounds
            if w > 100 and h > 100:
                if w != self._screen_width or h != self._screen_height:
                    self.logger.info(f"Screen dimensions detected: {w}x{h}")
                self._screen_width = w
                self._screen_height = h

    def set_cancel_checker(self, checker: Callable[[], Awaitable[None]] | None) -> None:
        """Set a cancel checker callback that will be called during long operations."""
        self._cancel_checker = checker

    async def _check_cancelled(self) -> None:
        """Check if operation should be cancelled. Raises exception if so."""
        if self._cancel_checker:
            await self._cancel_checker()

    # =========================================================================
    # App Management
    # =========================================================================

    async def launch_wecom(self, wait_for_ready: bool = True) -> None:
        """
        Launch the WeCom application.

        Args:
            wait_for_ready: If True, wait for the app to be ready
        """
        with log_operation(self.logger, "launch_wecom"):
            await self.adb.start_app(self.config.app.package_name)

            if wait_for_ready:
                await self.adb.wait(self.config.timing.wait_after_launch)

    # =========================================================================
    # Navigation
    # =========================================================================

    def _is_private_filter(self, value: str | None) -> bool:
        """Check if a filter label corresponds to Private Chats."""
        if not value:
            return False
        value_lower = value.lower()
        for pattern in self.config.app.private_chats_patterns:
            if pattern.lower() in value_lower or value_lower in pattern.lower():
                return True
        return False

    async def switch_to_private_chats(self, debug: bool = False) -> bool:
        """
        Switch the Messages tab filter to "Private chats".

        This method:
        1. Scrolls to the top of the Messages tab
        2. Clicks on the "All" dropdown menu
        3. Selects "Private chats" from the menu

        Args:
            debug: If True, log detailed UI information

        Returns:
            True if successfully switched or already on Private chats

        Raises:
            NavigationError: If navigation to Private chats fails
        """
        with log_operation(self.logger, "switch_to_private_chats"):
            # Step 1: Scroll to top
            await self.adb.scroll_to_top()
            await self.adb.wait(self.config.timing.ui_stabilization_delay)

            # Step 2: Get current UI state
            self.logger.info("Getting UI state...")
            elements = await self.adb.get_clickable_elements()

            if debug:
                self._log_ui_elements(elements)

            # Step 3: Check current filter
            current_filter = self.ui_parser.get_current_filter_text(elements)
            self.logger.info(f"Current filter: {current_filter or 'unknown'}")

            # Check if already on Private chats
            if self._is_private_filter(current_filter):
                self.logger.info("Already showing 'Private chats' - no action needed")
                return True

            # Step 4: Click current filter dropdown to open menu
            dropdown_opened = False

            # Try to find the dropdown trigger (could be 'All', 'External', etc.)
            all_element = self.ui_parser.find_element_by_text(
                elements,
                self.config.app.all_text_patterns,
            )

            if all_element:
                dropdown_index = all_element.get("index")
                if dropdown_index is not None:
                    self.logger.info(f"Clicking filter dropdown at index {dropdown_index}")
                    await self.adb.tap(dropdown_index)
                    await self.adb.wait(self.config.timing.tap_delay)

                    # Get updated UI state
                    elements = await self.adb.get_clickable_elements()
                    dropdown_opened = True
                    if debug:
                        self._log_ui_elements(elements, "after dropdown opened")
                else:
                    self.logger.warning("Filter dropdown element has no index")
            else:
                self.logger.info("Filter dropdown not found; attempting to locate options directly")

            # Step 5: Click "Private chats" option
            private_options = self.ui_parser.find_all_elements_by_text(
                elements,
                self.config.app.private_chats_patterns,
            )

            if not private_options:
                if dropdown_opened:
                    self.logger.error("Could not find 'Private chats' option in dropdown")
                else:
                    self.logger.error("Could not find 'Private chats' option; UI state may already be filtered")
                raise UIElementNotFoundError(
                    "Private chats option not found",
                    element_description="Private chats menu option",
                    search_patterns=list(self.config.app.private_chats_patterns),
                )

            private_element = private_options[0]
            private_index = private_element.get("index")

            if private_index is not None:
                self.logger.info(f"Clicking 'Private chats' at index {private_index}")
                await self.adb.tap(private_index)
                await self.adb.wait(self.config.timing.tap_delay)

                # Verify new state
                elements = await self.adb.get_clickable_elements()
                new_filter = self.ui_parser.get_current_filter_text(elements)
                if self._is_private_filter(new_filter):
                    self.logger.info("Successfully switched to 'Private chats'")
                    return True

                raise NavigationError(
                    "Failed to confirm 'Private chats' selection",
                    target="Private chats",
                    context={"filter_text": new_filter},
                )
            else:
                raise NavigationError(
                    "Could not tap 'Private chats' - no index available",
                    target="Private chats",
                )

    # =========================================================================
    # User Extraction
    # =========================================================================

    async def extract_private_chat_users(
        self,
        max_scrolls: int | None = None,
        capture_avatars: bool = False,
        output_dir: str | None = None,
    ) -> ExtractionResult:
        """
        Extract ALL users from the Private Chats list using robust scrolling.

        Strategy:
        1. Ensure top (3 stable checks).
        2. Scroll down and extract until NO NEW users found for 3 consecutive scrolls.
        """
        start_time = time.perf_counter()

        with log_operation(self.logger, "extract_private_chat_users"):
            # 1. Ensure Top (Robust)
            self.logger.info("Phase 1: ensuring top of list...")
            await self.adb.scroll_to_top()
            # Double check top stability
            for _ in range(3):
                if self.adb.is_tree_unchanged():
                    break
                await self.adb.scroll_to_top(scroll_count=1)
                await self.adb.wait(0.5)

            # 2. Extract Loop
            self.logger.info("Phase 2: extracting all users...")
            all_users: dict[str, UserDetail] = {}
            no_new_users_counter = 0
            MAX_NO_NEW_TRIES = 3
            total_scrolls = 0

            # Safety break to prevent infinite dead loop if something is really wrong
            # e.g. 10000 scrolls is likely enough for 50k users.
            SAFETY_LIMIT = 10000

            for i in range(SAFETY_LIMIT):
                total_scrolls = i

                # Check for skip request each scroll
                await self._check_cancelled()

                # Get Tree
                tree, _ = await self.adb.get_ui_state()
                if not tree:
                    self.logger.warning("Failed to get UI tree, retrying...")
                    await self.adb.wait(1.0)
                    continue

                # Extract
                current_users = self.ui_parser.extract_users_from_tree(tree)
                new_in_batch = 0

                for user in current_users:
                    key = user.unique_key()
                    if key not in all_users:
                        all_users[key] = user
                        new_in_batch += 1
                    else:
                        # Merge fields if needed
                        existing = all_users[key]
                        all_users[key] = existing.merge_with(user)

                self.logger.info(
                    f"Scroll {i}: Found {len(current_users)} in view, {new_in_batch} new. "
                    f"Total distinct: {len(all_users)}"
                )

                # Check stop condition
                if new_in_batch == 0:
                    no_new_users_counter += 1
                    if no_new_users_counter >= MAX_NO_NEW_TRIES:
                        self.logger.info(
                            f"Stop condition met: No new users for {MAX_NO_NEW_TRIES} scrolls. Reached bottom."
                        )
                        break
                else:
                    no_new_users_counter = 0

                # Scroll down
                await self.adb.scroll_down()
                await self.adb.wait(self.config.timing.scroll_delay)
                # Check for skip after scroll
                await self._check_cancelled()

            users = list(all_users.values())

            # Capture avatars if requested
            if capture_avatars and users:
                await self._capture_avatars(users, output_dir)

            # Log user list extraction swipe statistics
            self.adb.log_swipe_statistics("User list extraction")

            duration = time.perf_counter() - start_time

            return ExtractionResult(
                users=users,
                extraction_time=datetime.now(),
                total_scrolls=total_scrolls,
                duration_seconds=duration,
                success=True,
            )

    async def run_full_workflow(
        self,
        skip_launch: bool = False,
        capture_avatars: bool = False,
        output_dir: str | None = None,
    ) -> ExtractionResult:
        """
        Run the complete workflow:
        1. Launch WeCom (optional)
        2. Switch to Private Chats
        3. Extract all user details

        Args:
            skip_launch: If True, skip launching WeCom (assume already open)
            capture_avatars: If True, capture avatar screenshots
            output_dir: Directory for output files

        Returns:
            ExtractionResult containing all extracted users
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting full WeCom automation workflow")
        self.logger.info("=" * 60)

        try:
            # Step 1: Launch WeCom
            if not skip_launch:
                self.logger.info("Step 1: Launching WeCom...")
                await self.launch_wecom()
            else:
                self.logger.info("Step 1: Skipping launch (already open)")

            # Step 2: Switch to Private Chats
            self.logger.info("Step 2: Switching to Private Chats...")
            await self.switch_to_private_chats()
            await self.adb.wait(self.config.timing.ui_stabilization_delay)

            # Step 3: Extract users
            self.logger.info("Step 3: Extracting user details...")
            result = await self.extract_private_chat_users(
                capture_avatars=capture_avatars,
                output_dir=output_dir,
            )

            self.logger.info("=" * 60)
            self.logger.info(f"Workflow complete: {result.total_count} users extracted")
            self.logger.info("=" * 60)

            return result

        except Exception as e:
            self.logger.error(f"Workflow failed: {e}")
            return ExtractionResult(
                users=[],
                extraction_time=datetime.now(),
                success=False,
                error_message=str(e),
            )

    # =========================================================================
    # Avatar Capture
    # =========================================================================

    async def _capture_avatars(
        self,
        users: list[UserDetail],
        output_dir: str | None,
    ) -> None:
        """
        Capture avatar screenshots for all users.

        Args:
            users: List of users to capture avatars for
            output_dir: Directory to save avatars
        """
        try:
            from io import BytesIO

            from PIL import Image
        except ImportError:
            self.logger.warning("PIL not installed - skipping avatar capture")
            return

        output_dir = output_dir or self.config.output_dir
        avatar_dir = Path(output_dir) / "avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Capturing avatars to: {avatar_dir}")

        # Scroll to top first
        await self.adb.scroll_to_top()
        await self.adb.wait(self.config.timing.ui_stabilization_delay)

        # Track captured users
        captured_keys = set()
        entry_indices = {user.unique_key(): idx for idx, user in enumerate(users)}

        max_attempts = 10
        attempt = 0

        while len(captured_keys) < len(users) and attempt < max_attempts:
            attempt += 1

            # Check for skip request
            await self._check_cancelled()

            # Get current view
            tree, _ = await self.adb.get_ui_state()
            if not tree:
                await self.adb.scroll_down()
                continue

            current_users = self.ui_parser.extract_users_from_tree(tree)

            # Take screenshot
            try:
                _, image_bytes = await self.adb.take_screenshot()
                full_image = Image.open(BytesIO(image_bytes))
            except Exception as e:
                self.logger.error(f"Screenshot failed: {e}")
                continue

            # Process visible users
            captured_in_batch = 0

            for user in users:
                key = user.unique_key()
                if key in captured_keys:
                    continue

                # Find in current view
                current_user = next((u for u in current_users if u.unique_key() == key), None)

                if not current_user or not current_user.avatar:
                    continue

                if not current_user.avatar.parse_bounds():
                    continue

                # Validate bounds
                x1, y1, x2, y2 = (
                    current_user.avatar.x1,
                    current_user.avatar.y1,
                    current_user.avatar.x2,
                    current_user.avatar.y2,
                )

                img_width, img_height = full_image.size

                # Check bounds validity
                if x1 < 0 or y1 < 0 or x2 > img_width or y2 > img_height:
                    continue

                width, height = x2 - x1, y2 - y1
                if width < 30 or height < 30 or width > 300 or height > 300:
                    continue

                # Skip if too close to bottom (might be cut off)
                if y2 > img_height * 0.92:
                    continue

                # Crop and save
                try:
                    avatar_crop = full_image.crop((x1, y1, x2, y2))
                    idx = entry_indices[key]
                    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in user.name)
                    filename = f"avatar_{idx + 1:02d}_{safe_name}.png"
                    avatar_path = avatar_dir / filename

                    avatar_crop.save(avatar_path)
                    user.avatar.screenshot_path = str(avatar_path)
                    captured_keys.add(key)
                    captured_in_batch += 1
                    self.logger.info(f"Saved avatar: {filename}")

                except Exception as e:
                    self.logger.error(f"Failed to save avatar for {user.name}: {e}")

            # Scroll if needed
            if len(captured_keys) < len(users):
                await self.adb.scroll_down()
                await self.adb.wait(self.config.timing.scroll_delay)

        self.logger.info(f"Captured {len(captured_keys)}/{len(users)} avatars")

    async def screenshot_element(self, bounds_str: str, output_path: str) -> bool:
        """
        Screenshot a specific UI element by bounds and save to file.

        This method:
        1. Takes a full screenshot
        2. Crops to the specified element bounds
        3. Saves the cropped image to the output path

        This is used by AvatarManager to capture avatar images from the screen.

        Args:
            bounds_str: Element bounds in format "[x1,y1][x2,y2]"
            output_path: Path where the cropped screenshot should be saved

        Returns:
            True if screenshot was successful, False otherwise
        """
        if not HAS_PIL:
            self.logger.error("PIL not installed - cannot screenshot element")
            return False

        try:
            # Parse bounds string format: [x1,y1][x2,y2]
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
            if not match:
                self.logger.error(f"Invalid bounds format: {bounds_str}")
                return False

            x1, y1, x2, y2 = map(int, match.groups())

            # Validate bounds are logical
            if x1 >= x2 or y1 >= y2:
                self.logger.error(f"Invalid bounds: [{x1},{y1}][{x2},{y2}]")
                return False

            # Take full screenshot
            self.logger.debug(f"Taking screenshot to crop element: {bounds_str}")
            _, image_bytes = await self.adb.take_screenshot()
            full_image = Image.open(BytesIO(image_bytes))

            # Validate bounds are within image
            img_width, img_height = full_image.size
            if x1 < 0 or y1 < 0 or x2 > img_width or y2 > img_height:
                self.logger.error(
                    f"Bounds exceed image dimensions: bounds=[{x1},{y1}][{x2},{y2}], image={img_width}x{img_height}"
                )
                return False

            # Crop and save
            cropped = full_image.crop((x1, y1, x2, y2))

            # Ensure output directory exists
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            cropped.save(output_file)
            self.logger.info(f"Element screenshot saved: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to screenshot element {bounds_str}: {e}")
            return False

    async def get_ui_tree(self, refresh: bool = True) -> Any | None:
        """
        Get the current UI accessibility tree.

        This is a convenience method that delegates to ADBService.

        Args:
            refresh: If True, force a fresh UI tree fetch

        Returns:
            UI tree as dict/list, or None if fetch failed
        """
        return await self.adb.get_ui_tree(refresh=refresh)

    # =========================================================================
    # Conversation Message Extraction
    # =========================================================================

    async def extract_conversation_messages(
        self,
        max_scrolls: int | None = None,
        download_images: bool = True,
        download_videos: bool = True,
        download_voices: bool = True,
        output_dir: str | None = None,
    ) -> ConversationExtractionResult:
        """
        Extract all messages from the current conversation window.

        This method:
        1. Scrolls to the very top of the conversation (until stable)
        2. Scrolls down through the entire conversation, extracting messages (until end)
        3. **CAPTURES IMAGES INLINE** during scroll when they're visible (coordinates are accurate)
        4. **DOWNLOADS VIDEOS INLINE** during scroll - STOPS scrolling to save each video
        5. **DOWNLOADS VOICES INLINE** during scroll - plays voice to cache, then pulls SILK file
        6. Preserves discovery order (which is chronological when starting from top)
        7. Deduplicates using sequence-based overlap detection

        The extraction continues until the end is reached (stability-based),
        not limited by a fixed scroll count.

        IMPORTANT: Images, videos, and voices are captured during the scroll phase, NOT afterward.
        This ensures coordinates are accurate (the element is currently visible).
        For videos/voices, the scroll STOPS at each item to perform the download sequence.

        Args:
            max_scrolls: Safety limit for maximum scrolls (default: 500)
            download_images: If True, capture/crop image messages during scroll
            download_videos: If True, download video messages during scroll (STOPS scrolling)
            download_voices: If True, download voice messages during scroll (STOPS scrolling)
            output_dir: Directory for downloaded images, videos, and voices

        Returns:
            ConversationExtractionResult containing all messages and metadata
        """
        start_time = time.perf_counter()
        # Safety limit only - extraction stops when end is reached, not by count
        # Default to 500 if not specified, ignore config value (config is for other scroll operations)
        if max_scrolls is None:
            max_scrolls = 500
        output_dir = output_dir or self.config.output_dir
        self.logger.info(f"Extraction safety limit: {max_scrolls} scrolls")

        # Setup image directory if capturing images
        image_dir = None
        if download_images:
            # Fix nested path issue: avoid conversation_images/conversation_images/
            output_path = Path(output_dir)
            if "conversation_images" in output_path.name:
                image_dir = output_path
            else:
                image_dir = output_path / "conversation_images"
            image_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Images will be captured to: {image_dir}")

        # Setup video directory if downloading videos
        video_dir = None
        if download_videos:
            video_dir = Path(output_dir) / "conversation_videos"
            video_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Videos will be downloaded to: {video_dir}")

        # Setup voice directory if downloading voices
        voice_dir = None
        if download_voices:
            voice_dir = Path(output_dir) / "conversation_voices"
            voice_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Voices will be downloaded to: {voice_dir}")

        with log_operation(self.logger, "extract_conversation_messages"):
            # Get contact info from header
            tree, _ = await self.adb.get_ui_state()
            contact_name, contact_channel = self.ui_parser.get_conversation_header_info(tree)
            self.logger.info(f"Conversation with: {contact_name or 'Unknown'} ({contact_channel or 'N/A'})")

            # =============================================================
            # STEP 1: FAST SCROLL TO TOP (NO EXTRACTION)
            # =============================================================
            # Scroll aggressively without extracting until we reach the top.
            # No fixed limit - continues until UI stops changing.
            self.logger.info("Phase 1: Fast scroll to top (no extraction)...")

            last_tree_hash = None
            stable_count = 0
            scroll_up_count = 0

            while True:
                # Check for skip request before scroll
                await self._check_cancelled()

                # Fast scroll up
                await self.adb.swipe(540, 350, 540, 1300, 150)  # Quick swipe
                await self.adb.wait(0.25)  # Short wait

                # Check for skip request after scroll (reduce response delay)
                await self._check_cancelled()

                scroll_up_count += 1

                # Check if we've stopped scrolling (reached top)
                tree = await self.adb.get_ui_tree()
                if tree:
                    tree_hash = self.adb.hash_ui_tree(tree)
                    if tree_hash == last_tree_hash:
                        stable_count += 1
                        if stable_count >= 4:  # Need 4 stable reads to confirm top
                            self.logger.info(f"  Reached top after {scroll_up_count} scrolls")
                            break
                    else:
                        stable_count = 0
                        last_tree_hash = tree_hash

                # Safety limit to prevent infinite loops
                if scroll_up_count >= max_scrolls:
                    self.logger.warning(f"  Hit safety limit ({max_scrolls}) while scrolling to top")
                    break

            # Extra wait for UI to fully stabilize
            await self.adb.wait(0.8)

            # Log Phase 1 swipe statistics
            self.adb.log_swipe_statistics("Phase 1 fast scroll to top")

            # =============================================================
            # STEP 2: SLOW SCROLL DOWN WITH EXTRACTION
            # =============================================================
            # Now extract messages while scrolling down slowly.
            # This ensures chronological order and proper overlap detection.
            self.logger.info("Phase 2: Slow scroll down with extraction...")

            all_messages: list[ConversationMessage] = []
            # Fingerprint: (is_self, type, timestamp, content[:100])
            # MUST include timestamp to differentiate identical messages sent at different times
            all_fingerprints: list[tuple[bool, str, str, str]] = []

            # Initialize timestamp parser
            self.timestamp_parser.set_reference_time()

            def get_fingerprint(msg: ConversationMessage) -> tuple[bool, str, str, str]:
                """Create fingerprint including timestamp for identical messages."""
                content = (msg.content or "")[:100]
                timestamp = msg.timestamp or ""
                return (msg.is_self, msg.message_type, timestamp, content)

            def find_sequence_overlap(
                accumulated: list[tuple[bool, str, str, str]], current: list[tuple[bool, str, str, str]]
            ) -> int:
                """
                Find where new messages start using sequence matching.

                Strategy:
                1. First try to match the longest sequence at boundary
                2. If that fails, try to find any matching sequence in recent messages
                3. For single-message views, match against last accumulated
                """
                if not accumulated or not current:
                    return 0

                # Strategy 1: Find longest matching sequence at boundary
                # (end of accumulated == start of current)
                max_overlap = min(len(accumulated), len(current))
                for overlap_size in range(max_overlap, 0, -1):
                    if accumulated[-overlap_size:] == current[:overlap_size]:
                        return overlap_size

                # Strategy 2: Look for matching sequence in recent accumulated
                # This handles cases where scroll jumped slightly
                recent_window = min(20, len(accumulated))
                recent = accumulated[-recent_window:]

                # For each position in current, see if it matches something in recent
                for i in range(len(current)):
                    for j in range(len(recent) - 1, -1, -1):  # Search from end
                        if current[i] == recent[j]:
                            # Found a match - count consecutive matches
                            match_len = 1
                            while (
                                i + match_len < len(current)
                                and j + match_len < len(recent)
                                and current[i + match_len] == recent[j + match_len]
                            ):
                                match_len += 1

                            # Accept if we matched at least 1 message AND
                            # either matched multiple messages or the match is recent
                            if match_len >= 1 and (match_len >= 2 or j >= len(recent) - 3):
                                return i + match_len

                return 0  # No overlap found - all messages are new

            stable_count = 0
            total_scrolls = 0
            last_fps: list[tuple[bool, str, str, str]] = []
            extraction_pass = 0
            images_downloaded = 0
            videos_downloaded = 0
            voices_downloaded = 0
            captured_image_keys: set[str] = set()  # Track captured images by unique_key
            captured_video_keys: set[str] = set()  # Track captured videos by unique_key
            captured_voice_keys: set[str] = set()  # Track captured voices by unique_key

            while True:
                # Check for cancel request (allows Skip button to work during extraction)
                await self._check_cancelled()

                self.logger.info(f"Extraction pass {extraction_pass}")

                # Get UI tree
                tree = await self.adb.get_ui_tree()
                if not tree:
                    self.logger.error("  Failed to get UI tree")
                    await self.adb.wait(0.5)
                    continue

                # Extract messages from current view
                current_messages = self.ui_parser.extract_conversation_messages(tree)
                current_fps = [get_fingerprint(m) for m in current_messages]

                self.logger.debug(f"  Visible: {len(current_messages)} messages")

                # Skip if no messages
                if not current_messages:
                    stable_count += 1
                    if stable_count >= 3:
                        self.logger.info("  No messages visible - stopping")
                        break
                    await self.adb.scroll_down()
                    await self.adb.wait(0.5)
                    # Check for skip after scroll
                    await self._check_cancelled()
                    total_scrolls += 1
                    continue

                # Check if view is unchanged (stuck)
                if current_fps == last_fps:
                    stable_count += 1
                    if stable_count >= self.config.scroll.stable_threshold:
                        self.logger.info("  View unchanged - extraction complete")
                        break
                else:
                    last_fps = current_fps[:]

                # Find overlap using strict sequence matching
                new_start = find_sequence_overlap(all_fingerprints, current_fps)

                # Add only messages after the overlap
                new_messages = current_messages[new_start:]
                new_fps = current_fps[new_start:]

                if new_messages:
                    # =============================================================
                    # INLINE IMAGE CAPTURE - capture images NOW while visible
                    # =============================================================
                    # This is the key fix: capture images during scroll when
                    # coordinates are accurate, NOT after scrolling completes.
                    if download_images and image_dir and HAS_PIL:
                        # Take screenshot ONCE for all images in this batch
                        # (more efficient than one screenshot per image)
                        try:
                            _, screenshot_bytes = await self.adb.take_screenshot()
                            full_screenshot = Image.open(BytesIO(screenshot_bytes))
                            img_width, img_height = full_screenshot.size

                            for msg in new_messages:
                                if msg.message_type == "image" and msg.image:
                                    # Capture this image now while it's visible
                                    captured = await self._capture_image_inline(
                                        msg,
                                        full_screenshot,
                                        img_width,
                                        img_height,
                                        image_dir,
                                        len(all_messages) + new_messages.index(msg) + 1,
                                        captured_image_keys,
                                    )
                                    if captured:
                                        images_downloaded += 1
                        except Exception as e:
                            self.logger.warning(f"Screenshot failed during inline capture: {e}")

                    # =============================================================
                    # INLINE VIDEO DOWNLOAD - STOP scrolling, download video, then continue
                    # =============================================================
                    # Videos require user interaction (click -> long press -> save to phone)
                    # We MUST stop scrolling to download each video while it's visible
                    if download_videos and video_dir:
                        for msg in new_messages:
                            if msg.message_type == "video":
                                # CRITICAL: Stop here and download the video inline
                                # This ensures coordinates are still valid
                                msg_idx = len(all_messages) + new_messages.index(msg) + 1
                                video_path = await self._download_video_inline(
                                    msg,
                                    video_dir,
                                    msg_idx,
                                    captured_video_keys,
                                )
                                if video_path:
                                    videos_downloaded += 1
                                    # Store the path in the message for later use
                                    msg.video_local_path = video_path

                    # =============================================================
                    # INLINE VOICE DOWNLOAD - STOP scrolling, play voice to cache, then pull
                    # =============================================================
                    # Voice messages are only cached when played. We need to:
                    # 1. Click voice to start playback (caches SILK file)
                    # 2. Wait for cache file to appear
                    # 3. Pull SILK file from /sdcard/Android/data/com.tencent.wework/files/voicemsg/
                    # 4. Convert SILK to WAV using pilk library
                    if download_voices and voice_dir:
                        for msg in new_messages:
                            # Download ALL voice messages (both from self and from customer)
                            # Voice messages from customers are especially important for analysis
                            if msg.message_type == "voice":
                                msg_idx = len(all_messages) + new_messages.index(msg) + 1
                                voice_path = await self._download_voice_inline(
                                    msg,
                                    voice_dir,
                                    msg_idx,
                                    captured_voice_keys,
                                )
                                if voice_path:
                                    voices_downloaded += 1
                                    msg.voice_local_path = voice_path

                    all_messages.extend(new_messages)
                    all_fingerprints.extend(new_fps)
                    stable_count = 0
                    self.logger.info(f"  overlap={new_start}, added={len(new_messages)}, total={len(all_messages)}")
                else:
                    stable_count += 1
                    self.logger.info(f"  overlap={new_start}, no new messages")

                # Check if we've reached the end (stability)
                if stable_count >= self.config.scroll.stable_threshold:
                    self.logger.info("  Extraction complete - reached end of conversation")
                    break

                # Safety limit
                if extraction_pass >= max_scrolls:
                    self.logger.warning(f"  Hit safety limit ({max_scrolls} passes)")
                    break

                # Scroll down with medium speed
                await self.adb.swipe(540, 1100, 540, 500, 300)
                await self.adb.wait(0.6)
                # Check for skip after scroll
                await self._check_cancelled()
                total_scrolls += 1
                extraction_pass += 1

            # Images, videos, and voices are now captured inline during scroll, not afterward
            self.logger.info(
                f"Inline capture complete: {images_downloaded} images, {videos_downloaded} videos, {voices_downloaded} voices"
            )

            # Log Phase 2 swipe statistics
            self.adb.log_swipe_statistics("Phase 2 message extraction")

            duration = time.perf_counter() - start_time

            return ConversationExtractionResult(
                messages=all_messages,
                contact_name=contact_name,
                contact_channel=contact_channel,
                extraction_time=datetime.now(),
                total_scrolls=total_scrolls,
                duration_seconds=duration,
                success=True,
                images_downloaded=images_downloaded,
                videos_downloaded=videos_downloaded,
                voices_downloaded=voices_downloaded,
            )

    async def _download_video_inline(
        self,
        msg: ConversationMessage,
        video_dir: Path,
        msg_index: int,
        captured_keys: set[str],
    ) -> str | None:
        """
        Download a video message INLINE during scroll extraction.

        This method is called immediately when a video message is detected,
        STOPPING the scroll to download the video before continuing.

        The process:
        1. Click on the video to open fullscreen view
        2. Long-press to show the share/save menu
        3. Click "Save to phone" button
        4. Wait for download to complete
        5. Pull the video from device /sdcard/DCIM/WeixinWork/
        6. Verify the pulled video is correct (by timestamp and file existence)

        Args:
            msg: The ConversationMessage with video info
            video_dir: Directory to save videos
            msg_index: Message index for filename
            captured_keys: Set of already captured video keys (for deduplication)

        Returns:
            Path to saved video file, or None if failed
        """
        if msg.message_type != "video":
            return None

        # Skip if already captured (deduplication)
        video_key = msg.unique_key()
        if video_key in captured_keys:
            self.logger.debug(f"Video already captured: {video_key[:50]}...")
            return None

        self.logger.info(f"=== INLINE VIDEO DOWNLOAD for message {msg_index} ===")

        # Get bounds from the video thumbnail (stored in msg.image)
        if not msg.image or not msg.image.parse_bounds():
            self.logger.warning(f"Video message {msg_index} has no valid bounds")
            return None

        x1, y1, x2, y2 = msg.image.x1, msg.image.y1, msg.image.x2, msg.image.y2
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2

        self.logger.info(f"Video bounds: [{x1},{y1}][{x2},{y2}], center: ({center_x},{center_y})")

        # Record timestamp BEFORE starting download (for verification)
        import subprocess
        import time as time_module

        time_module.time()

        # Get the bundled ADB path
        adb_exe = _get_project_adb_path()
        self.logger.debug(f"Using ADB: {adb_exe}")

        # Get list of existing videos on device for verification
        device_serial = self.config.device_serial
        try:
            result = subprocess.run(
                [adb_exe, "-s", device_serial, "shell", "ls -la /sdcard/DCIM/WeixinWork/*.mp4 2>/dev/null || true"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            existing_videos_before = set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()
            self.logger.debug(f"Existing videos before: {len(existing_videos_before)}")
        except Exception as e:
            self.logger.warning(f"Could not list existing videos: {e}")
            existing_videos_before = set()

        try:
            # STEP 1: Click on video to open fullscreen
            self.logger.info("Step 1: Clicking on video to open fullscreen...")
            await self.adb.tap_coordinates(center_x, center_y)
            await self.adb.wait(1.5)  # Wait for fullscreen to open

            # STEP 2: Long-press on the video to show menu
            self.logger.info("Step 2: Long-pressing to show save menu...")
            await self.adb.long_press(center_x, center_y, duration_ms=1500)
            await self.adb.wait(1.0)  # Wait for menu to appear

            # STEP 3: Find and click "Save to phone" button
            self.logger.info("Step 3: Looking for 'Save to phone' button...")

            # Get current UI to find the Save to phone button
            elements = await self.adb.get_clickable_elements()

            save_button = None
            save_button_patterns = ("save to phone", "保存到手机", "保存")

            for element in elements:
                text = (element.get("text") or "").lower().strip()
                content_desc = (element.get("contentDescription") or "").lower().strip()

                for pattern in save_button_patterns:
                    if pattern in text or pattern in content_desc:
                        save_button = element
                        self.logger.info(f"Found save button with text: '{text}'")
                        break
                if save_button:
                    break

            if save_button:
                index = save_button.get("index")
                if index is not None:
                    self.logger.info(f"Clicking 'Save to phone' at index {index}")
                    await self.adb.tap(index)
                else:
                    # Try to click by bounds
                    bounds = self._parse_element_bounds(save_button)
                    if bounds:
                        bx1, by1, bx2, by2 = bounds
                        await self.adb.tap_coordinates((bx1 + bx2) // 2, (by1 + by2) // 2)
                    else:
                        self.logger.warning("Save button has no index or bounds")
                        await self._cleanup_video_download_state()
                        return None
            else:
                # Fallback: Based on the UI images, "Save to phone" is typically at index 10
                # or in the 4th position (around x=396, based on typical button layout)
                self.logger.warning("Could not find 'Save to phone' button by text, using fallback position")
                # From the images: Save to phone appears to be around (396, 858) based on typical layout
                # The button row is at y~830-860 area
                # Try tapping where "Save to phone" typically is (4th button in row)
                await self.adb.tap_coordinates(396, 858)

            await self.adb.wait(2.0)  # Wait for save to start

            # STEP 4: Wait for download to complete and verify
            self.logger.info("Step 4: Waiting for video to save...")

            # Poll for new video file on device
            max_wait_seconds = 30
            poll_interval = 1.0
            elapsed = 0.0
            new_video_path = None

            while elapsed < max_wait_seconds:
                # Check for skip request
                await self._check_cancelled()

                await self.adb.wait(poll_interval)
                elapsed += poll_interval

                try:
                    # List videos sorted by modification time (newest first)
                    result = subprocess.run(
                        [
                            adb_exe,
                            "-s",
                            device_serial,
                            "shell",
                            "ls -t /sdcard/DCIM/WeixinWork/*.mp4 2>/dev/null | head -1",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    newest_video = result.stdout.strip()

                    if newest_video and newest_video.endswith(".mp4"):
                        # Check if this is a new file (not in our existing list)
                        result2 = subprocess.run(
                            [adb_exe, "-s", device_serial, "shell", f"ls -la '{newest_video}' 2>/dev/null"],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        current_video_info = result2.stdout.strip()

                        if current_video_info and current_video_info not in existing_videos_before:
                            # Verify file is not still being written (size stable)
                            await self.adb.wait(0.5)
                            result3 = subprocess.run(
                                [adb_exe, "-s", device_serial, "shell", f"stat -c '%s' '{newest_video}' 2>/dev/null"],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            size1 = result3.stdout.strip()

                            await self.adb.wait(0.5)
                            result4 = subprocess.run(
                                [adb_exe, "-s", device_serial, "shell", f"stat -c '%s' '{newest_video}' 2>/dev/null"],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            size2 = result4.stdout.strip()

                            if size1 == size2 and size1:
                                # File size is stable, download complete
                                new_video_path = newest_video
                                self.logger.info(f"Found new video: {newest_video} (size: {size1} bytes)")
                                break
                            else:
                                self.logger.debug(f"Video still downloading: {size1} -> {size2}")
                        else:
                            self.logger.debug(f"No new video yet (elapsed: {elapsed:.1f}s)")

                except subprocess.TimeoutExpired:
                    self.logger.warning("Timeout checking for video")
                except Exception as e:
                    self.logger.warning(f"Error checking for video: {e}")

            if not new_video_path:
                self.logger.warning(f"Video download not detected after {max_wait_seconds}s")
                await self._cleanup_video_download_state()
                return None

            # STEP 5: Pull the video from device
            self.logger.info(f"Step 5: Pulling video from device: {new_video_path}")

            video_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"video_{msg_index}_{timestamp}.mp4"
            local_path = video_dir / filename

            try:
                pull_result = subprocess.run(
                    [adb_exe, "-s", device_serial, "pull", new_video_path, str(local_path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if pull_result.returncode != 0 or not local_path.exists():
                    self.logger.error(f"Failed to pull video: {pull_result.stderr}")
                    await self._cleanup_video_download_state()
                    return None

                file_size = local_path.stat().st_size
                self.logger.info(f"Successfully pulled video: {filename} ({file_size} bytes)")

            except subprocess.TimeoutExpired:
                self.logger.error("Video pull timed out")
                await self._cleanup_video_download_state()
                return None

            # Mark as captured
            captured_keys.add(video_key)

            # Update the message's video info with local path
            if not hasattr(msg, "video_local_path"):
                msg.video_local_path = str(local_path)

            # STEP 6: Clean up and return to conversation
            self.logger.info("Step 6: Returning to conversation view...")
            await self._cleanup_video_download_state()

            self.logger.info(f"=== VIDEO DOWNLOAD COMPLETE: {filename} ===")
            return str(local_path)

        except Exception as e:
            self.logger.error(f"Video download failed: {e}")
            await self._cleanup_video_download_state()
            return None

    async def _cleanup_video_download_state(self) -> None:
        """
        Clean up after video download attempt.

        Press back ONCE and verify we're back in conversation view.
        Only press back again if needed. This prevents over-pressing which
        could exit the conversation or even the WeCom app.
        """
        self.logger.debug("Cleaning up video download state...")

        max_back_presses = 2  # Maximum: 1 for menu dismiss, 1 for video exit

        for i in range(max_back_presses):
            try:
                await self.adb.press_back()
                await self.adb.wait(0.8)  # Wait for UI to stabilize

                # Check if we're back in conversation view
                tree = await self.adb.get_ui_tree()
                if tree:
                    # Check if we can see conversation messages (indicates we're in conversation)
                    messages = self.ui_parser.extract_conversation_messages(tree)
                    if messages:
                        self.logger.debug(f"Back in conversation view after {i + 1} back press(es)")
                        return

                    # Alternative check: look for message input field (indicates conversation view)
                    elements = await self.adb.get_clickable_elements()
                    for element in elements:
                        class_name = (element.get("className") or "").lower()
                        rid = (element.get("resourceId") or "").lower()
                        text = (element.get("text") or "").lower()
                        # Input field indicators
                        if "edittext" in class_name or "input" in rid:
                            self.logger.debug(f"Found input field - back in conversation after {i + 1} back press(es)")
                            return
                        # Also check for send button which indicates conversation view
                        if "send" in text or "发送" in text or "ie3" in rid or "iew" in rid:
                            self.logger.debug(f"Found send button - back in conversation after {i + 1} back press(es)")
                            return

            except Exception as e:
                self.logger.warning(f"Error during cleanup back press: {e}")

        self.logger.debug(f"Cleanup completed after {max_back_presses} back presses")

    async def _download_voice_inline(
        self,
        msg: ConversationMessage,
        voice_dir: Path,
        msg_index: int,
        captured_keys: set[str],
    ) -> str | None:
        """
        Download a voice message INLINE during scroll extraction.

        Voice messages in WeCom are only cached when played. The process:
        1. Record existing SILK files in the cache directory
        2. Click on the voice message to start playback (this caches the SILK file)
        3. Wait for a new SILK file to appear in the cache
        4. Pull the SILK file from device
        5. Convert SILK to WAV using pilk library

        Voice cache location: /sdcard/Android/data/com.tencent.wework/files/voicemsg/{user_id}/

        Args:
            msg: The ConversationMessage with voice info
            voice_dir: Directory to save voice files
            msg_index: Message index for filename
            captured_keys: Set of already captured voice keys (for deduplication)

        Returns:
            Path to saved WAV file, or None if failed
        """
        import subprocess

        if msg.message_type != "voice":
            return None

        # Skip if already captured (deduplication)
        voice_key = msg.unique_key()
        if voice_key in captured_keys:
            self.logger.debug(f"Voice already captured: {voice_key[:50]}...")
            return None

        self.logger.info(f"=== INLINE VOICE DOWNLOAD for message {msg_index} ===")
        self.logger.info(f"Voice duration: {msg.voice_duration}")

        # Get the center of the voice message bubble for clicking
        # Voice messages use raw_bounds from the message row
        if not msg.raw_bounds:
            self.logger.warning(f"Voice message {msg_index} has no bounds")
            return None

        # Parse raw bounds
        import re as re_module

        bounds_match = re_module.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", msg.raw_bounds)
        if not bounds_match:
            self.logger.warning(f"Could not parse voice bounds: {msg.raw_bounds}")
            return None

        x1, y1, x2, y2 = map(int, bounds_match.groups())

        # For self messages, voice bubble is on the right side
        # For other messages, voice bubble is on the left side
        # Adjust click position to be in the voice bubble area
        if msg.is_self:
            # Self message: voice bubble is on the right, roughly x=350-550
            center_x = min(x2 - 150, 500)  # A bit left from the avatar
        else:
            # Other message: voice bubble is on the left, roughly x=100-350
            center_x = max(x1 + 200, 200)  # A bit right from the avatar
        center_y = (y1 + y2) // 2

        self.logger.info(f"Voice bounds: [{x1},{y1}][{x2},{y2}], clicking at: ({center_x},{center_y})")

        device_serial = self.config.device_serial
        voice_cache_path = "/sdcard/Android/data/com.tencent.wework/files/voicemsg/"

        # Get the bundled ADB path
        adb_exe = _get_project_adb_path()
        self.logger.debug(f"Using ADB: {adb_exe}")

        # Helper to build adb command with or without serial
        def adb_cmd(*args) -> list:
            if device_serial:
                return [adb_exe, "-s", device_serial] + list(args)
            return [adb_exe] + list(args)

        try:
            # STEP 1: Get list of existing SILK files BEFORE click
            self.logger.info("Step 1: Recording existing voice files...")
            result = subprocess.run(
                adb_cmd("shell", f"find {voice_cache_path} -name '*.silk' -type f 2>/dev/null | sort"),
                capture_output=True,
                text=True,
                timeout=10,
            )
            existing_files_list = [f for f in result.stdout.strip().split("\n") if f.endswith(".silk")]
            existing_files = set(existing_files_list)
            self.logger.debug(f"Existing SILK files: {len(existing_files)}")

            # STEP 2: Click on voice to start playback (this will cache if not already cached)
            self.logger.info("Step 2: Clicking voice to trigger playback/caching...")
            await self.adb.tap_coordinates(center_x, center_y)

            # Wait for voice to be cached (depends on duration, but usually quick)
            # Parse duration like "2\"" or "3\"" to get seconds
            wait_time = 2.0  # Default wait time
            duration_secs = 2
            if msg.voice_duration:
                try:
                    duration_secs = int(msg.voice_duration.replace('"', "").replace("'", ""))
                    wait_time = max(duration_secs + 1.0, 2.0)  # Wait at least duration + 1s
                except ValueError:
                    pass

            await self.adb.wait(wait_time)

            # STEP 3: Match SILK by basename YYYY_MM_DD + UI duration (byte band + score); relax if needed
            target_cal = _voice_message_calendar_date(msg)
            if target_cal:
                self.logger.info(f"Step 3: Matching SILK (filename date={target_cal} + duration~{duration_secs}s)")
            else:
                self.logger.info(
                    "Step 3: No message timestamp — match SILK by duration~"
                    f"{duration_secs}s (any filename date, then relax band)"
                )

            result = subprocess.run(
                adb_cmd("shell", f"find {voice_cache_path} -name '*.silk' -type f 2>/dev/null | sort"),
                capture_output=True,
                text=True,
                timeout=10,
            )
            current_files_list = [f for f in result.stdout.strip().split("\n") if f.endswith(".silk")]
            current_files = set(current_files_list)

            new_files = current_files - existing_files
            target_silk_file = None

            if new_files:
                target_silk_file = _select_silk_by_date_and_duration(
                    adb_cmd,
                    sorted(new_files),
                    target_date=target_cal,
                    duration_secs=duration_secs,
                    captured_keys=captured_keys,
                    logger=self.logger,
                )
                if not target_silk_file:
                    target_silk_file = sorted(new_files)[-1]
                    self.logger.warning(
                        "New SILK on device but date+duration selection failed; using last new path lexically: %s",
                        target_silk_file,
                    )
                else:
                    self.logger.info(f"Found newly cached SILK (date+duration pick): {target_silk_file}")
            elif current_files_list:
                target_silk_file = _select_silk_by_date_and_duration(
                    adb_cmd,
                    current_files_list,
                    target_date=target_cal,
                    duration_secs=duration_secs,
                    captured_keys=captured_keys,
                    logger=self.logger,
                )
                if not target_silk_file:
                    for silk_file in sorted(current_files_list, key=_silk_dt_sort_tuple, reverse=True):
                        if silk_file not in captured_keys:
                            target_silk_file = silk_file
                            self.logger.warning(
                                "Date+duration match failed; fallback to newest uncaptured basename: %s",
                                target_silk_file,
                            )
                            break

            if not target_silk_file:
                self.logger.warning("No suitable SILK file found")
                return None

            # STEP 4: Pull the SILK file
            self.logger.info("Step 4: Pulling SILK file from device...")

            voice_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            silk_filename = f"voice_{msg_index}_{timestamp}.silk"
            wav_filename = f"voice_{msg_index}_{timestamp}.wav"
            silk_local = voice_dir / silk_filename
            wav_local = voice_dir / wav_filename

            pull_result = subprocess.run(
                adb_cmd("pull", target_silk_file, str(silk_local)), capture_output=True, text=True, timeout=30
            )

            if pull_result.returncode != 0 or not silk_local.exists():
                self.logger.error(f"Failed to pull SILK file: {pull_result.stderr}")
                return None

            silk_size = silk_local.stat().st_size
            self.logger.info(f"Pulled SILK file: {silk_filename} ({silk_size} bytes)")

            # STEP 5: Convert SILK to WAV
            self.logger.info("Step 5: Converting SILK to WAV...")

            try:
                import wave

                import pilk

                # pilk.decode outputs raw PCM data, not WAV
                # We need to decode to a temp PCM file, then wrap it in a proper WAV container
                pcm_local = voice_dir / f"temp_{msg_index}.pcm"

                # Decode SILK to raw PCM
                pilk.decode(str(silk_local), str(pcm_local))

                if pcm_local.exists():
                    # Read raw PCM data
                    pcm_data = pcm_local.read_bytes()

                    # SILK typically decodes to 24000 Hz, 16-bit, mono
                    sample_rate = 24000
                    sample_width = 2  # 16-bit = 2 bytes
                    channels = 1

                    # Write proper WAV file
                    with wave.open(str(wav_local), "wb") as wav_file:
                        wav_file.setnchannels(channels)
                        wav_file.setsampwidth(sample_width)
                        wav_file.setframerate(sample_rate)
                        wav_file.writeframes(pcm_data)

                    # Clean up temp PCM file
                    pcm_local.unlink()

                    wav_size = wav_local.stat().st_size
                    duration_secs = len(pcm_data) / (sample_rate * sample_width * channels)
                    self.logger.info(f"Converted to WAV: {wav_filename} ({wav_size} bytes, {duration_secs:.1f}s)")

                    # Clean up SILK file (keep only WAV)
                    silk_local.unlink()

                    # Mark as captured (both the message key and the source file path)
                    captured_keys.add(voice_key)
                    captured_keys.add(target_silk_file)  # Prevent reusing same source file

                    self.logger.info(f"=== VOICE DOWNLOAD COMPLETE: {wav_filename} ===")
                    return str(wav_local)
                else:
                    self.logger.error("PCM file not created after decoding")
                    return None

            except ImportError:
                self.logger.warning("pilk library not installed - keeping SILK file")
                captured_keys.add(voice_key)
                captured_keys.add(target_silk_file)
                return str(silk_local)
            except Exception as e:
                self.logger.error(f"SILK to WAV conversion failed: {e}")
                import traceback

                self.logger.debug(traceback.format_exc())
                # Return SILK path if conversion fails
                captured_keys.add(voice_key)
                captured_keys.add(target_silk_file)
                return str(silk_local)

        except subprocess.TimeoutExpired:
            self.logger.error("Voice download operation timed out")
            return None
        except Exception as e:
            self.logger.error(f"Voice download failed: {e}")
            import traceback

            self.logger.debug(traceback.format_exc())
            return None

    async def _capture_image_inline(
        self,
        msg: ConversationMessage,
        full_screenshot: Image.Image,
        img_width: int,
        img_height: int,
        image_dir: Path,
        msg_index: int,
        captured_keys: set[str],
    ) -> bool:
        """
        Capture an image message INLINE during scroll extraction.

        This method is called immediately when an image message is detected,
        while the image is still visible on screen. This ensures accurate
        cropping with correct coordinates.

        Args:
            msg: The ConversationMessage with image info
            full_screenshot: PIL Image of current screen
            img_width: Screenshot width
            img_height: Screenshot height
            image_dir: Directory to save images
            msg_index: Message index for filename
            captured_keys: Set of already captured image keys (for deduplication)

        Returns:
            True if image was captured successfully
        """
        if not msg.image:
            return False

        # Skip if already captured (deduplication)
        image_key = msg.unique_key()
        if image_key in captured_keys:
            self.logger.debug(f"Image already captured: {image_key[:50]}...")
            return False

        # Parse bounds
        if not msg.image.parse_bounds():
            self.logger.warning(f"Could not parse image bounds for msg {msg_index}")
            return False

        x1, y1, x2, y2 = msg.image.x1, msg.image.y1, msg.image.x2, msg.image.y2

        # Validate bounds are within screen
        if x1 < 0 or y1 < 0 or x2 > img_width or y2 > img_height:
            self.logger.debug(f"Image bounds outside screen: [{x1},{y1}][{x2},{y2}]")
            return False

        # Check minimum size
        width, height = x2 - x1, y2 - y1
        if width < 50 or height < 50:
            self.logger.debug(f"Image too small: {width}x{height}")
            return False

        # Skip images that are partially cut off (at screen edges)
        # Images near top/bottom edges may be partially scrolled off
        margin = 50
        if y1 < margin or y2 > img_height - margin:
            self.logger.debug(f"Image too close to edge: y1={y1}, y2={y2}, screen_h={img_height}")
            return False

        try:
            # Crop the image from screenshot
            image_crop = full_screenshot.crop((x1, y1, x2, y2))

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"msg_{msg_index}_{timestamp}.png"
            image_path = image_dir / filename

            # Save the cropped image
            image_crop.save(image_path)

            # Update the message's image info with local path
            msg.image.local_path = str(image_path)

            # Mark as captured
            captured_keys.add(image_key)

            self.logger.info(f"Captured image: {filename} ({width}x{height})")
            return True

        except Exception as e:
            self.logger.error(f"Failed to capture image: {e}")
            return False

    async def _download_conversation_images(
        self,
        messages: list[ConversationMessage],
        output_dir: str,
    ) -> int:
        """
        DEPRECATED: This method is kept for backwards compatibility but is no longer
        used by extract_conversation_messages(). Images are now captured inline
        during the scroll extraction phase.

        The problem with this method: it scrolls AFTER extraction is complete,
        so the stored coordinates no longer match the current screen position.
        The inline capture approach solves this by capturing images immediately
        when they're visible during the initial extraction scroll.

        Args:
            messages: List of messages (modified in place)
            output_dir: Directory to save images

        Returns:
            Number of images downloaded
        """
        # Log deprecation warning
        self.logger.warning(
            "_download_conversation_images is deprecated. "
            "Images should be captured inline during extraction. "
            "This method may produce incorrect results due to coordinate mismatch."
        )

        if not HAS_PIL:
            self.logger.warning("PIL not installed - skipping image download")
            return 0

        # Fix nested path issue: avoid conversation_images/conversation_images/
        output_path = Path(output_dir)
        if "conversation_images" in output_path.name:
            image_dir = output_path
        else:
            image_dir = output_path / "conversation_images"
        image_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Downloading conversation images to: {image_dir}")

        # Scroll to top first
        await self.adb.scroll_to_top()
        await self.adb.wait(self.config.timing.ui_stabilization_delay)

        # Track downloaded images
        downloaded_keys = set()
        image_messages = [m for m in messages if m.message_type == "image" and m.image]

        if not image_messages:
            return 0

        max_attempts = 15
        attempt = 0

        while len(downloaded_keys) < len(image_messages) and attempt < max_attempts:
            attempt += 1

            # Check for skip request
            await self._check_cancelled()

            # Take screenshot
            try:
                _, image_bytes = await self.adb.take_screenshot()
                full_image = Image.open(BytesIO(image_bytes))
                img_width, img_height = full_image.size
            except Exception as e:
                self.logger.error(f"Screenshot failed: {e}")
                continue

            # Get current visible messages to find correct bounds
            tree = await self.adb.get_ui_tree()
            if not tree:
                continue

            current_messages = self.ui_parser.extract_conversation_messages(tree)

            # Process visible image messages
            downloaded_in_batch = 0

            for msg in image_messages:
                key = msg.unique_key()
                if key in downloaded_keys:
                    continue

                # Find this message in current view
                current_msg = next((m for m in current_messages if m.unique_key() == key), None)

                if not current_msg or not current_msg.image:
                    continue

                if not current_msg.image.parse_bounds():
                    continue

                # Validate bounds
                x1, y1, x2, y2 = (
                    current_msg.image.x1,
                    current_msg.image.y1,
                    current_msg.image.x2,
                    current_msg.image.y2,
                )

                # Check bounds validity
                if x1 < 0 or y1 < 0 or x2 > img_width or y2 > img_height:
                    continue

                width, height = x2 - x1, y2 - y1
                if width < 50 or height < 50:
                    continue

                # Skip if too close to edges (might be cut off)
                if y1 < 100 or y2 > img_height - 100:
                    continue

                # Crop and save
                try:
                    image_crop = full_image.crop((x1, y1, x2, y2))
                    idx = messages.index(msg)
                    filename = f"msg_{idx + 1:03d}_image.png"
                    image_path = image_dir / filename

                    image_crop.save(image_path)
                    msg.image.local_path = str(image_path)
                    downloaded_keys.add(key)
                    downloaded_in_batch += 1
                    self.logger.info(f"Saved image: {filename}")

                except Exception as e:
                    self.logger.error(f"Failed to save image: {e}")

            # Scroll if needed
            if len(downloaded_keys) < len(image_messages):
                await self.adb.scroll_down()
                await self.adb.wait(self.config.timing.scroll_delay)

        self.logger.info(f"Downloaded {len(downloaded_keys)}/{len(image_messages)} images")
        return len(downloaded_keys)

    async def _download_image_via_fullscreen(
        self,
        image_info: ImageInfo,
        output_path: Path,
    ) -> bool:
        """
        Download an image by clicking it to open in fullscreen, then taking a screenshot.

        This method is more reliable than cropping from the conversation view because:
        1. It doesn't depend on scroll position or stale bounds
        2. The fullscreen view shows the complete image without UI elements
        3. DroidRun can reliably recognize the image element when it's visible

        Args:
            image_info: ImageInfo with bounds and/or resource_id
            output_path: Path where the image should be saved

        Returns:
            True if image was successfully downloaded, False otherwise
        """
        try:
            from io import BytesIO

            from PIL import Image
        except ImportError:
            self.logger.warning("PIL not installed - cannot download image")
            return False

        try:
            # Refresh UI state to get current clickable elements
            await self.adb.refresh_state(force=True)
            clickable_elements = self.adb._cache.clickable_elements

            # Find the image element by matching bounds or resource ID
            image_element = None

            if image_info.parse_bounds():
                # Try to find element by matching bounds (with some tolerance)
                target_bounds = (image_info.x1, image_info.y1, image_info.x2, image_info.y2)
                tolerance = 20  # Allow 20px tolerance for bounds matching

                for element in clickable_elements:
                    element_bounds = self._parse_element_bounds(element)
                    if element_bounds:
                        ex1, ey1, ex2, ey2 = element_bounds
                        # Check if bounds are close (within tolerance)
                        if (
                            abs(ex1 - target_bounds[0]) <= tolerance
                            and abs(ey1 - target_bounds[1]) <= tolerance
                            and abs(ex2 - target_bounds[2]) <= tolerance
                            and abs(ey2 - target_bounds[3]) <= tolerance
                        ):
                            # Also check if it's an ImageView
                            class_name = (element.get("className") or "").lower()
                            if "imageview" in class_name or "image" in class_name:
                                image_element = element
                                self.logger.debug(f"Found image element by bounds: {target_bounds}")
                                break

            # If not found by bounds, try resource ID
            if not image_element and image_info.resource_id:
                for element in clickable_elements:
                    rid = (element.get("resourceId") or "").lower()
                    if image_info.resource_id.lower() in rid:
                        class_name = (element.get("className") or "").lower()
                        if "imageview" in class_name or "image" in class_name:
                            image_element = element
                            self.logger.debug(f"Found image element by resource ID: {rid}")
                            break

            # Fallback: if we have bounds but couldn't match, try finding large ImageView elements
            # This helps when the image is visible but bounds have shifted slightly
            if not image_element and image_info.parse_bounds():
                target_width = image_info.width
                target_height = image_info.height

                for element in clickable_elements:
                    class_name = (element.get("className") or "").lower()
                    if "imageview" not in class_name and "image" not in class_name:
                        continue

                    # Skip avatars (they have 'im4' in resource ID and are small)
                    rid = (element.get("resourceId") or "").lower()
                    if "im4" in rid:
                        continue

                    element_bounds = self._parse_element_bounds(element)
                    if element_bounds:
                        ex1, ey1, ex2, ey2 = element_bounds
                        width = ex2 - ex1
                        height = ey2 - ey1

                        # Match if size is similar (within 30%) and looks like in-chat thumbnail
                        if (
                            message_image_thumbnail_min_ok(width, height)
                            and abs(width - target_width) / max(target_width, 1) < 0.3
                            and abs(height - target_height) / max(target_height, 1) < 0.3
                        ):
                            image_element = element
                            self.logger.debug(f"Found image element by size match: {width}x{height}")
                            break

            if not image_element:
                self.logger.warning("Could not find image element in clickable elements")
                return False

            # Click on the image element to open it in fullscreen
            self.logger.debug("Clicking image to open in fullscreen...")
            index = image_element.get("index")
            if index is not None:
                await self.adb.tap_by_index(index, refresh_first=False)
            else:
                # Fallback to coordinates
                bounds = self._parse_element_bounds(image_element)
                if bounds:
                    x1, y1, x2, y2 = bounds
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    await self.adb.tap_coordinates(center_x, center_y)
                else:
                    self.logger.error("Image element has no index or bounds")
                    return False

            # Wait for fullscreen view to open
            await self.adb.wait(1.5)

            # Take screenshot of the fullscreen image
            self.logger.debug("Taking screenshot of fullscreen image...")
            _, image_bytes = await self.adb.take_screenshot()
            fullscreen_image = Image.open(BytesIO(image_bytes))

            # Save the fullscreen image
            fullscreen_image.save(output_path)
            self.logger.info(f"Saved fullscreen image: {output_path}")

            # Press back to return to conversation
            await self.adb.press_back()
            await self.adb.wait(1.0)

            return True

        except Exception as e:
            self.logger.error(f"Failed to download image via fullscreen: {e}")
            # Try to press back in case we're stuck in fullscreen
            try:
                await self.adb.press_back()
            except Exception:
                pass
            return False

    async def _download_conversation_images(
        self,
        messages: list[ConversationMessage],
        output_dir: str,
    ) -> int:
        """
        Download/screenshot images from conversation messages.

        Uses the fullscreen method: clicks on each image to open it in fullscreen,
        takes a screenshot, then presses back. This is more reliable than cropping
        from the conversation view.

        Args:
            messages: List of messages (modified in place)
            output_dir: Directory to save images

        Returns:
            Number of images downloaded
        """
        # Fix nested path issue: avoid conversation_images/conversation_images/
        output_path = Path(output_dir)
        if "conversation_images" in output_path.name:
            image_dir = output_path
        else:
            image_dir = output_path / "conversation_images"
        image_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Downloading conversation images to: {image_dir}")

        # Scroll to top first
        await self.adb.scroll_to_top()
        await self.adb.wait(self.config.timing.ui_stabilization_delay)

        # Track downloaded images
        downloaded_keys = set()
        image_messages = [m for m in messages if m.message_type == "image" and m.image]

        if not image_messages:
            return 0

        max_attempts = 15
        attempt = 0

        while len(downloaded_keys) < len(image_messages) and attempt < max_attempts:
            attempt += 1

            # Check for skip request
            await self._check_cancelled()

            # Get current visible messages
            tree = await self.adb.get_ui_tree()
            if not tree:
                continue

            current_messages = self.ui_parser.extract_conversation_messages(tree)

            # Process visible image messages
            downloaded_in_batch = 0

            for msg in image_messages:
                key = msg.unique_key()
                if key in downloaded_keys:
                    continue

                # Find this message in current view
                current_msg = next((m for m in current_messages if m.unique_key() == key), None)

                if not current_msg or not current_msg.image:
                    continue

                # Try to download via fullscreen method
                idx = messages.index(msg)
                filename = f"msg_{idx + 1:03d}_image.png"
                image_path = image_dir / filename

                success = await self._download_image_via_fullscreen(current_msg.image, image_path)

                if success:
                    msg.image.local_path = str(image_path)
                    downloaded_keys.add(key)
                    downloaded_in_batch += 1
                    self.logger.info(f"Downloaded image: {filename}")

            # Scroll if needed
            if len(downloaded_keys) < len(image_messages):
                await self.adb.scroll_down()
                await self.adb.wait(self.config.timing.scroll_delay)

        self.logger.info(f"Downloaded {len(downloaded_keys)}/{len(image_messages)} images")
        return len(downloaded_keys)

    # =========================================================================
    # Kefu (Customer Service Rep) Information
    # =========================================================================

    async def get_kefu_name(self, debug: bool = False) -> KefuInfo | None:
        """
        Get the 客服 (Customer Service Rep) name from the current UI.

        The 客服 name is extracted directly from the UI tree without
        needing to fold/unfold the interface.

        Args:
            debug: If True, log detailed UI information

        Returns:
            KefuInfo with the extracted name, or None if extraction failed
        """
        with log_operation(self.logger, "get_kefu_name"):
            self.logger.info("Extracting 客服 name from UI tree...")

            tree = await self.adb.get_ui_tree()

            if debug:
                elements = await self.adb.get_clickable_elements()
                self._log_ui_elements(elements, "current view")

            kefu_info = self.ui_parser.extract_kefu_info_from_tree(tree)

            if kefu_info:
                self.logger.info(f"Successfully extracted 客服 name: {kefu_info.name}")
            else:
                self.logger.warning("Could not extract 客服 name")

            return kefu_info

    # =========================================================================
    # Message Sending
    # =========================================================================

    async def send_message(self, text: str) -> tuple[bool, str]:
        """
        Send a text message in the current conversation.

        This method:
        1. Finds and taps the input field
        2. Types the message text
        3. Taps the send button

        Optimized: Uses get_ui_state() for single ADB call instead of
        multiple get_clickable_elements() calls. Uses is_flat_list=True
        to skip unnecessary recursion.

        Args:
            text: The message text to send

        Returns:
            Tuple of (success, actual_message_sent).
            The actual_message_sent is the same as text for normal mode,
            but may differ when AI reply is used in sidecar mode.
        """
        with log_operation(self.logger, "send_message"):
            try:
                # Get both UI tree and clickable elements in single call
                ui_tree, elements = await self.adb.get_ui_state()

                # Find input field (optimized for flat list)
                input_field = self._find_input_field(elements, is_flat_list=True)
                if input_field:
                    input_index = input_field.get("index")
                    if input_index is not None:
                        self.logger.info(f"Tapping input field at index {input_index}")
                        await self.adb.tap(input_index)
                        await self.adb.wait(self.config.timing.tap_delay)

                # P0 改进: 清空输入框中的残留文本（防止断连后重复发送）
                # Clear any existing text in input field to prevent duplicate sends
                await self._clear_input_field()

                # Input the text
                self.logger.info(f"Typing message: {text[:50]}...")
                await self.adb.input_text(text)
                await self.adb.wait(self.config.timing.ui_stabilization_delay)

                # Refresh state after typing (UI may have changed)
                ui_tree, elements = await self.adb.get_ui_state(force=True)

                # Find send button (optimized for flat list)
                send_button = self._find_send_button(elements, is_flat_list=True)

                if send_button:
                    self.logger.info("Tapping send button (clickable list)")
                    if await self._tap_element(send_button):
                        await self.adb.wait(self.config.timing.tap_delay)
                        self.logger.info("Message sent successfully")
                        return True, text

                # Fallback: try to locate send button in full UI tree for bounds
                if ui_tree:
                    tree_send_button = self._find_send_button(ui_tree)
                    if tree_send_button:
                        self.logger.info("Tapping send button (UI tree fallback)")
                        if await self._tap_element(
                            tree_send_button,
                            fallback_coords=self.config.app.send_button_coordinates,
                        ):
                            await self.adb.wait(self.config.timing.tap_delay)
                            self.logger.info("Message sent successfully")
                            return True, text

                # Final fallback: press Enter key to send
                self.logger.info("Send button not found, pressing Enter key")
                await self.adb.press_enter()
                await self.adb.wait(self.config.timing.tap_delay)
                return True, text

            except Exception as e:
                self.logger.error(f"Failed to send message: {e}")
                return False, text

    def _find_input_field(self, elements: list[dict], is_flat_list: bool = False) -> dict | None:
        """
        Find the message input field in the UI.

        Args:
            elements: List of UI elements to search
            is_flat_list: If True, skip recursive child search (optimized for
                         flat lists like clickable_elements_cache)
        """
        input_hints = ("edittext", "input", "输入", "type", "compose", "说点什么")

        for element in elements:
            class_name = (element.get("className") or "").lower()
            text = (element.get("text") or "").lower()
            rid = (element.get("resourceId") or "").lower()

            # Check class name
            if "edittext" in class_name or "edit" in class_name:
                return element

            # Check text/hints
            for hint in input_hints:
                if hint in text or hint in rid:
                    return element

            # Only check children recursively if not a flat list
            if not is_flat_list:
                children = element.get("children", [])
                if children:
                    result = self._find_input_field(children, is_flat_list=False)
                    if result:
                        return result

        return None

    async def _clear_input_field(self) -> None:
        """
        Clear any existing text in the input field.

        This is a P0 improvement to prevent issues when:
        1. Connection was lost while typing - residual text remains
        2. Resuming after disconnect - prevents duplicate/merged messages

        Uses multiple Delete key presses to clear text reliably.
        """
        try:
            self.logger.debug("Clearing input field...")

            # Use the adb_service's clear_text_field method which presses DEL key multiple times
            # This is more reliable than Ctrl+A which may not work on all devices
            await self.adb.clear_text_field()

            self.logger.debug("Input field cleared")

        except Exception as e:
            # Non-critical - just log and continue
            self.logger.warning(f"Failed to clear input field: {e}")

    def _find_send_button(
        self,
        elements: list[dict],
        is_flat_list: bool = False,
        _depth: int = 0,
    ) -> dict | None:
        """
        Find the send button in the UI.

        Enhanced strategy:
        1. Precise match first: Button class + SEND/发送 text (highest priority)
        2. Keyword match: check text, resourceId, contentDescription
        3. Recursive search with depth limit (max 30 levels)

        Args:
            elements: List of UI elements to search
            is_flat_list: If True, skip recursive child search (optimized for
                         flat lists like clickable_elements_cache)
            _depth: Internal recursion depth counter (max 30)
        """
        # Depth limit to prevent infinite recursion
        if _depth > 30:
            return None

        # Extended hints: ie3/iew/idf are common WeCom resource IDs
        send_hints = ("send", "发送", "ie3", "iew", "idf")
        preferred_send_ids = ("igu",)

        iterable = elements
        if isinstance(elements, dict):
            iterable = [elements]

        # Phase 1: Precise match - Button class with SEND/发送 text (highest priority)
        for element in iterable:
            class_name = (element.get("class") or element.get("className") or "").lower()
            text = (element.get("text") or "").lower()
            rid = (element.get("resourceId") or "").lower()

            # Precise match: Button + (SEND text or idf resourceId)
            if "button" in class_name:
                if "send" in text or "发送" in text or "idf" in rid:
                    return element

        # Phase 2: Keyword match - check all hints in text/rid/contentDescription
        for element in iterable:
            text = (element.get("text") or "").lower()
            rid = (element.get("resourceId") or "").lower()
            content_desc = (element.get("contentDescription") or "").lower()

            for hint in send_hints:
                if hint in text or hint in rid or hint in content_desc:
                    return element

            # Phase 3: Recursive search (only if not flat list)
            if not is_flat_list:
                children = element.get("children", [])
                if children:
                    result = self._find_send_button(children, is_flat_list=False, _depth=_depth + 1)
                    if result:
                        return result

        # Phase 4: Heuristic fallback for newer WeCom builds where the send
        # control is an unlabeled ImageView to the right of the EditText.
        input_field = None
        if isinstance(iterable, list):
            input_field = self._find_input_field(iterable, is_flat_list=is_flat_list)

        input_bounds = self._parse_element_bounds(input_field)
        if input_bounds:
            _, input_top, input_right, input_bottom = input_bounds
            input_center_y = (input_top + input_bottom) // 2

            candidates: list[tuple[int, int, dict]] = []
            for element in iterable:
                class_name = (element.get("class") or element.get("className") or "").lower()
                rid = (element.get("resourceId") or "").lower()
                bounds = self._parse_element_bounds(element)
                if not bounds:
                    continue

                x1, y1, x2, y2 = bounds
                center_y = (y1 + y2) // 2
                width = x2 - x1
                height = y2 - y1

                is_action_class = any(token in class_name for token in ("imageview", "imagebutton", "button"))
                is_same_row = abs(center_y - input_center_y) <= 140
                is_to_right = x1 >= input_right - 10
                is_compact = width <= 220 and height <= 220

                if not (is_action_class and is_same_row and is_to_right and is_compact):
                    continue

                # Prefer known send ids, otherwise pick the rightmost action.
                priority = 1 if any(pid in rid for pid in preferred_send_ids) else 0
                candidates.append((priority, x2, element))

            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
                return candidates[0][2]

        return None

    async def _tap_element(
        self,
        element: dict,
        fallback_coords: tuple[int, int] | None = None,
    ) -> bool:
        """
        Tap a UI element using its index or bounds.

        Args:
            element: UI element dictionary
            fallback_coords: Optional coordinates to use if index/bounds missing
        """
        index = element.get("index")
        if index is not None:
            await self.adb.tap(index)
            return True

        bounds = self._parse_element_bounds(element)
        if bounds:
            x1, y1, x2, y2 = bounds
            x = (x1 + x2) // 2
            y = (y1 + y2) // 2
            await self.adb.tap_coordinates(x, y)
            return True

        if fallback_coords:
            await self.adb.tap_coordinates(*fallback_coords)
            return True

        return False

    def _parse_element_bounds(self, element: dict | None) -> tuple[int, int, int, int] | None:
        """
        Parse bounds from an element dict.
        Supports both string bounds ("[x1,y1][x2,y2]") and dict bounds
        (bounds/boundsInScreen keys).
        """
        if not element:
            return None

        bounds_value = element.get("bounds")
        if not bounds_value:
            bounds_value = element.get("boundsInScreen") or element.get("bounds_in_screen")

        if not bounds_value:
            return None

        if isinstance(bounds_value, dict):
            return (
                int(bounds_value.get("left", 0)),
                int(bounds_value.get("top", 0)),
                int(bounds_value.get("right", 0)),
                int(bounds_value.get("bottom", 0)),
            )

        if isinstance(bounds_value, str):
            nums = re.findall(r"-?\d+", bounds_value)
            if len(nums) >= 4:
                x1, y1, x2, y2 = (int(n) for n in nums[:4])
                return (x1, y1, x2, y2)

        return None

    def _is_group_chat_title(self, value: str | None) -> bool:
        """Heuristic for external/group chat titles in WeCom."""
        if not value:
            return False

        normalized = value.lower()
        return any(
            keyword in normalized
            for keyword in (
                "group chat",
                "external group",
                "enter group name",
                "群聊",
                "外部群",
                "外部客户群",
            )
        )

    def _looks_like_bottom_input(
        self,
        bounds: tuple[int, int, int, int] | None,
        viewport_bottom: int,
    ) -> bool:
        """Treat an input as bottom composer using a relative viewport threshold."""
        if not bounds:
            return False

        _, top, _, bottom = bounds
        effective_bottom = max(viewport_bottom, bottom, 1)
        threshold = max(600, int(effective_bottom * 0.55))
        return top >= threshold or bottom >= max(900, int(effective_bottom * 0.7))

    async def wait_for_new_messages(
        self,
        timeout_seconds: float = 5.0,
        check_interval: float = 1.0,
    ) -> list[ConversationMessage]:
        """
        Wait for new messages to appear in the conversation.

        This method polls the conversation view and returns any new messages
        that appear within the timeout period.

        Args:
            timeout_seconds: Maximum time to wait for new messages
            check_interval: Time between checks

        Returns:
            List of new messages that appeared
        """
        with log_operation(self.logger, "wait_for_new_messages"):
            # Get initial message set
            tree = await self.adb.get_ui_tree()
            initial_messages = self.ui_parser.extract_conversation_messages(tree)
            initial_keys = {msg.unique_key() for msg in initial_messages}

            self.logger.info(f"Initial message count: {len(initial_messages)}")

            # Poll for new messages
            elapsed = 0.0
            new_messages: list[ConversationMessage] = []

            while elapsed < timeout_seconds:
                # Check for skip request each iteration
                await self._check_cancelled()

                await self.adb.wait(check_interval)
                elapsed += check_interval

                tree = await self.adb.get_ui_tree()
                current_messages = self.ui_parser.extract_conversation_messages(tree)

                # Find new messages
                for msg in current_messages:
                    key = msg.unique_key()
                    if key not in initial_keys:
                        new_messages.append(msg)
                        initial_keys.add(key)
                        self.logger.info(
                            f"New message detected: {msg.content[:50] if msg.content else '[non-text]'}..."
                        )

                if new_messages:
                    self.logger.info(f"Found {len(new_messages)} new message(s)")
                    return new_messages

            self.logger.info("No new messages within timeout")
            return []

    # =========================================================================
    # User Navigation
    # =========================================================================

    async def click_user_in_list(
        self,
        user_name: str,
        channel: str | None = None,
        pre_click_callback: Callable | None = None,
    ) -> bool:
        """
        Click on a user in the private chats list.

        Args:
            user_name: Name of the user to click
            channel: Optional channel filter (e.g., "@WeChat")
            pre_click_callback: Optional async callback to execute after finding user
                               but before clicking. Signature: async def callback(user_name: str)
                               This is useful for capturing avatar while user is visible.

        Returns:
            True if user was found and clicked
        """
        with log_operation(self.logger, "click_user_in_list", user=user_name):
            # Check for skip request before starting
            await self._check_cancelled()

            # Scroll to top first
            await self.adb.scroll_to_top()
            await self.adb.wait(self.config.timing.ui_stabilization_delay)

            max_attempts = self.config.scroll.max_scrolls

            for attempt in range(max_attempts):
                # Check for skip request each iteration
                await self._check_cancelled()

                self.logger.debug(f"Search attempt {attempt + 1}/{max_attempts}")

                # Get current UI state
                elements = await self.adb.get_clickable_elements()

                # Look for the user
                user_element = self._find_user_element(elements, user_name, channel)

                if user_element:
                    user_index = user_element.get("index")
                    if user_index is not None:
                        self.logger.info(f"Found user '{user_name}' at index {user_index}")

                        # Execute pre-click callback (e.g., capture avatar while user is visible)
                        if pre_click_callback:
                            try:
                                self.logger.info(f"Executing pre-click callback for '{user_name}'")
                                await pre_click_callback(user_name)
                            except Exception as e:
                                self.logger.warning(f"Pre-click callback failed: {e}")

                        await self.adb.tap(user_index)
                        await self.adb.wait(self.config.timing.tap_delay)
                        self.logger.info(f"Clicked on user '{user_name}'")
                        return True

                # Scroll down and try again
                await self.adb.scroll_down()
                await self.adb.wait(self.config.timing.scroll_delay)

            self.logger.warning(f"User '{user_name}' not found after {max_attempts} scrolls")
            return False

    def _find_user_element(
        self,
        elements: list[dict],
        user_name: str,
        channel: str | None,
        is_flat_list: bool = False,
    ) -> dict | None:
        """
        Find a user element in the clickable elements list.

        Args:
            elements: List of UI elements to search
            user_name: User name to find
            channel: Optional channel filter
            is_flat_list: If True, skip recursive child search (optimized for
                         flat lists like clickable_elements_cache)
        """
        user_name_lower = user_name.lower()

        for element in elements:
            text = (element.get("text") or "").strip()

            if text.lower() == user_name_lower:
                # If channel specified, verify it matches
                if channel:
                    # Check siblings or nearby elements for channel
                    # For now, we just match by name
                    pass
                return element

            # Only check children recursively if not a flat list
            if not is_flat_list:
                children = element.get("children", [])
                if children:
                    result = self._find_user_element(children, user_name, channel, is_flat_list=False)
                    if result:
                        # Return the parent if the child itself isn't clickable
                        if not result.get("clickable") and element.get("clickable"):
                            return element
                        return result

        return None

    # =========================================================================
    # Screen State Detection (for Resume Sync)
    # =========================================================================

    async def get_current_screen(self) -> str:
        """
        Detect the current screen state of the phone.

        Used for Resume Sync to determine what action is needed
        before continuing the sync.

        Returns:
            'chat': In a chat conversation screen
            'private_chats': In the private chats list
            'other': In other WeCom screens (settings, contacts, etc.)
            'unknown': Cannot determine the screen state
        """
        self.logger.info("🔍 Detecting current screen state...")

        try:
            tree = await self.adb.get_ui_tree()
            if not tree:
                self.logger.warning("Could not get UI tree for screen detection")
                return "unknown"

            # Get clickable elements for analysis
            elements = await self.adb.get_clickable_elements(refresh=False)

            # Log some elements for debugging
            self.logger.debug(f"Found {len(elements)} clickable elements")
            for i, el in enumerate(elements[:10]):  # First 10 elements
                text = el.get("text", "")
                desc = el.get("contentDescription", "")
                cls = el.get("className", "").split(".")[-1]
                rid = el.get("resourceId", "").split("/")[-1] if el.get("resourceId") else ""
                self.logger.debug(f"  [{i}] {cls}: text='{text}', desc='{desc}', rid='{rid}'")

            # Check for chat screen indicators:
            # - Has back button (返回) in top-left
            # - Has input field (EditText) at bottom
            # - Has send button
            if self._is_chat_screen(tree, elements):
                self.logger.info("✅ Current screen: chat (conversation)")
                return "chat"

            # Check for private chats list indicators:
            # - Has "私聊" tab or filter
            # - Has user list items
            if self._is_private_chats_screen(tree, elements):
                self.logger.info("✅ Current screen: private_chats (list)")
                return "private_chats"

            # Check if we're in WeCom app at all
            if self._is_in_wecom_app(tree):
                self.logger.info("⚠️ Current screen: other (WeCom app)")
                return "other"

            self.logger.warning("❓ Current screen: unknown")
            return "unknown"

        except Exception as e:
            self.logger.error(f"Failed to detect screen state: {e}")
            return "unknown"

    def _is_chat_screen(self, tree: Any, elements: list[dict]) -> bool:
        """Check if current screen is a chat conversation."""
        has_back_button = False
        has_input_field = False
        has_bottom_input_field = False
        has_send_button = False
        has_message_list = False
        has_group_chat_hint = False
        viewport_bottom = 0

        def update_viewport_bottom(element: dict | None) -> None:
            nonlocal viewport_bottom
            bounds = self._parse_element_bounds(element)
            if bounds:
                viewport_bottom = max(viewport_bottom, bounds[3])

        for element in elements:
            text = (element.get("text") or "").lower()
            content_desc = (element.get("contentDescription") or "").lower()
            class_name = (element.get("className") or "").lower()
            resource_id = (element.get("resourceId") or "").lower()
            update_viewport_bottom(element)

            # Check for back button (multiple patterns)
            back_patterns = ["返回", "back", "navigate", "arrow", "left"]
            if any(kw in content_desc for kw in back_patterns):
                has_back_button = True
            # Also check ImageButton in top area (index 0-5) as back button
            if "imagebutton" in class_name or "imageview" in class_name:
                idx = element.get("index", 999)
                if idx is not None and idx < 5:
                    has_back_button = True

            # Check for input field
            bounds = self._parse_element_bounds(element)
            if "edittext" in class_name:
                has_input_field = True
                if self._looks_like_bottom_input(bounds, viewport_bottom):
                    has_bottom_input_field = True
            # Also check resource_id for input
            if any(kw in resource_id for kw in ["input", "edit", "compose", "message_input"]):
                has_input_field = True
                if self._looks_like_bottom_input(bounds, viewport_bottom):
                    has_bottom_input_field = True

            # Check for send button
            if (
                any(kw in text for kw in ["发送", "send"])
                or any(kw in content_desc for kw in ["发送", "send"])
                or "send" in resource_id
            ):
                has_send_button = True

            # Check for chat-specific resource IDs (WeCom specific)
            chat_resource_patterns = [
                "chat",
                "conversation",
                "message_list",
                "msg_list",
                "chat_list",
                "recyclerview",
                "listview",
            ]
            if any(kw in resource_id for kw in chat_resource_patterns):
                has_message_list = True
            # Message area is often a ListView/RecyclerView whose resource id does not contain "chat"
            if "listview" in class_name or "recyclerview" in class_name:
                has_message_list = True

            raw_title = element.get("text") or ""
            raw_desc = element.get("contentDescription") or ""
            if self._is_group_chat_title(raw_title) or self._is_group_chat_title(raw_desc):
                has_group_chat_hint = True

        # Also check the raw tree for chat indicators
        def check_tree_for_chat(node):
            nonlocal has_input_field, has_bottom_input_field, has_message_list, has_group_chat_hint
            if not isinstance(node, dict):
                return False

            rid = (node.get("resourceId") or "").lower()
            cls = (node.get("className") or "").lower()
            text = (node.get("text") or "").lower()
            content_desc = (node.get("contentDescription") or "").lower()
            bounds = self._parse_element_bounds(node)
            update_viewport_bottom(node)

            if self._is_group_chat_title(text) or self._is_group_chat_title(content_desc):
                has_group_chat_hint = True

            if "edittext" in cls:
                has_input_field = True
                if self._looks_like_bottom_input(bounds, viewport_bottom):
                    has_bottom_input_field = True

            # Chat screen typically has a RecyclerView/ListView for messages
            if "recyclerview" in cls or "listview" in cls:
                has_message_list = True
                if "chat" in rid or "message" in rid or "conversation" in rid:
                    return True

            # Check children
            for child in node.get("children", []):
                if check_tree_for_chat(child):
                    return True
            return False

        # Walk tree for side effects on has_* flags; do not OR the return value —
        # check_tree_for_chat often returns False after setting has_message_list.
        if isinstance(tree, dict):
            check_tree_for_chat(tree)
        elif isinstance(tree, list):
            for item in tree:
                check_tree_for_chat(item)

        # Debug logging
        self.logger.debug(
            f"Chat screen detection: back={has_back_button}, input={has_input_field}, "
            f"bottom_input={has_bottom_input_field}, group_hint={has_group_chat_hint}, "
            f"send={has_send_button}, msg_list={has_message_list}"
        )

        # Chat screen detection logic:
        # Option 1: has back button + input field
        # Option 2: has back button + send button
        # Option 3: has back button + message list
        # Option 4: has input field + message list (even without visible back)
        if has_back_button and (has_bottom_input_field or has_send_button or has_message_list):
            return True
        if has_bottom_input_field and has_message_list:
            return True
        if has_back_button and has_group_chat_hint and (has_bottom_input_field or has_message_list):
            return True
        if has_group_chat_hint and has_input_field and has_back_button:
            return True
        if has_group_chat_hint and has_input_field and has_message_list:
            return True

        return False

    def _is_private_chats_screen(self, tree: Any, elements: list[dict]) -> bool:
        """Check if current screen is the private chats list."""
        has_private_chat_tab = False
        has_message_tab = False
        has_bottom_nav = False

        for element in elements:
            text = (element.get("text") or "").lower()
            resource_id = (element.get("resourceId") or "").lower()

            # Check for private chats tab/filter
            if any(kw in text for kw in ["私聊", "private"]):
                has_private_chat_tab = True

            # Check for messages tab indicator
            if text in ["消息", "messages", "message"]:
                has_message_tab = True

            # Check for bottom navigation (WeCom main screen)
            if any(kw in text for kw in ["工作台", "通讯录", "我"]):
                has_bottom_nav = True

            # Check resource ID patterns for main screen
            if any(kw in resource_id for kw in ["tab_", "bottom_nav", "navigation"]):
                has_bottom_nav = True

        self.logger.debug(
            f"Private chats detection: private_tab={has_private_chat_tab}, "
            f"msg_tab={has_message_tab}, bottom_nav={has_bottom_nav}"
        )

        return has_private_chat_tab or (has_message_tab and has_bottom_nav)

    def _is_in_wecom_app(self, tree: Any) -> bool:
        """Check if we're in the WeCom app."""
        if not tree:
            return False

        # Check for WeCom package name in the tree
        def check_element(element):
            if isinstance(element, dict):
                resource_id = element.get("resourceId") or ""
                if "com.tencent.wework" in resource_id:
                    return True
                for child in element.get("children", []):
                    if check_element(child):
                        return True
            return False

        if isinstance(tree, list):
            for item in tree:
                if check_element(item):
                    return True
        else:
            return check_element(tree)

        return False

    async def ensure_on_private_chats(self) -> bool:
        """
        Ensure we're on the private chats list screen.

        Detects current screen and navigates back if needed.
        Used before resuming sync.

        Returns:
            True if successfully on private chats screen
        """
        screen = await self.get_current_screen()

        if screen == "private_chats":
            self.logger.info("Already on private chats screen")
            return True

        if screen == "chat":
            self.logger.info("In chat screen, going back...")
            await self.go_back()
            await self.adb.wait(0.5)
            screen = await self.get_current_screen()
            if screen == "private_chats":
                return True
            self.logger.info(f"Landed on '{screen}' after go_back, switching to private chats...")
            try:
                await self.switch_to_private_chats()
                return True
            except Exception as e:
                self.logger.error(f"Failed to switch to private chats after go_back: {e}")
                return False

        if screen in ("other", "unknown"):
            self.logger.info("In other screen, navigating to private chats...")
            try:
                await self.switch_to_private_chats()
                return True
            except Exception as e:
                self.logger.error(f"Failed to navigate to private chats: {e}")
                return False

        return False

    async def go_back(self) -> None:
        """
        Go back from a conversation to the chat list.

        This clicks the back arrow (←) in the upper left corner of the
        conversation window, which is the WeCom-specific way to navigate back.

        Optimized: Uses get_ui_state() for single ADB call instead of
        separate get_ui_tree() and get_clickable_elements() calls.
        """
        with log_operation(self.logger, "go_back"):
            # Get both UI tree and clickable elements in single call
            ui_tree, clickable_elements = await self.adb.get_ui_state()

            # The back arrow is typically:
            # - An ImageView or ImageButton with content-desc containing "返回" or "back"
            # - Located in the top-left area (usually first clickable element)
            # - May have resource-id containing "back" or "navigate"
            # Search flat list first (no recursion), then tree as fallback
            back_button = self._find_back_button(clickable_elements)
            if not back_button:
                back_button = self._find_back_button(ui_tree)

            if back_button:
                self.logger.info("Attempting to tap detected back button")
                tapped = await self._tap_element(
                    back_button,
                    fallback_coords=self.config.app.back_button_coordinates,
                )
                if not tapped:
                    self.logger.warning("Detected back button but could not tap - using fallback coordinates")
                    await self.adb.tap_coordinates(*self.config.app.back_button_coordinates)
            else:
                # If we can't find the back button, tap the typical location
                self.logger.warning(
                    f"Could not find back button, tapping default location {self.config.app.back_button_coordinates}"
                )
                await self.adb.tap_coordinates(*self.config.app.back_button_coordinates)

            await self.adb.wait(self.config.timing.ui_stabilization_delay)

    def _find_back_button(self, ui_tree: object | None) -> dict | None:
        """
        Find the back button element in the UI tree.

        The back button is typically:
        - In the top-left area
        - Has content-desc containing "返回", "back", "Navigate up"
        - Or is the first clickable ImageView/ImageButton

        Args:
            ui_tree: The UI element tree

        Returns:
            The back button element if found, None otherwise
        """
        if not ui_tree:
            return None

        if isinstance(ui_tree, dict):
            elements = [ui_tree]
        else:
            elements = ui_tree

        def search_elements(elements: list[dict], depth: int = 0) -> dict | None:
            if depth > 10:  # Prevent infinite recursion
                return None

            for element in elements:
                if not isinstance(element, dict):
                    continue
                # Check content-desc for back-related text
                content_desc = element.get("contentDescription", "") or ""
                content_desc_lower = content_desc.lower()

                if any(keyword in content_desc_lower for keyword in ["返回", "back", "navigate up", "navigate_up"]):
                    return element

                # Check visible text for arrow characters
                text = (element.get("text") or "").strip()
                text_lower = text.lower()
                if text in {"←", "<"} or any(keyword in text_lower for keyword in ["返回", "back"]):
                    return element

                # Check resource-id for back-related identifiers
                resource_id = element.get("resourceId", "") or ""
                resource_id_lower = resource_id.lower()

                if any(keyword in resource_id_lower for keyword in ["back", "navigate", "返回", "ngl"]):
                    return element

                # Look for ImageButton or ImageView that's clickable in top area
                class_name = element.get("className", "")
                bounds = self._parse_element_bounds(element)

                # Check if it's a clickable image element in the top-left quadrant
                if bounds:
                    x1, y1, x2, y2 = bounds
                    if "ImageButton" in class_name or "ImageView" in class_name or "TextView" in class_name:
                        if y2 <= 400 and x2 <= 300:
                            return element

                # Recursively search children
                children = element.get("children", [])
                if children:
                    result = search_elements(children, depth + 1)
                    if result:
                        return result

            return None

        return search_elements(elements)

    # =========================================================================
    # Group Invite Navigation
    # =========================================================================

    async def navigate_to_chat(self, device_serial: str, customer_name: str) -> bool:
        """Open a customer's chat from the private-chats list."""
        _ = device_serial
        if not await self.ensure_on_private_chats():
            return False
        return await self.click_user_in_list(customer_name)

    async def open_chat_info(self, device_serial: str) -> bool:
        """Open the chat information screen from a chat conversation."""
        _ = device_serial
        ui_tree, elements = await self.adb.get_ui_state(force=True)
        self._update_screen_dimensions(elements)
        menu_button = self._find_group_invite_menu_button(elements)
        if not menu_button and ui_tree:
            menu_button = self._find_group_invite_menu_button([ui_tree], is_flat_list=False)

        if not menu_button:
            self.logger.warning("Could not find chat info menu button")
            return False

        if not await self._tap_element(menu_button):
            self.logger.warning("Could not tap chat info menu button")
            return False

        await self.adb.wait(self.config.timing.tap_delay)
        return True

    async def tap_add_member_button(self, device_serial: str) -> bool:
        """Tap the add-member entry from the chat info screen."""
        _ = device_serial
        ui_tree, elements = await self.adb.get_ui_state(force=True)
        self._update_screen_dimensions(elements)
        add_button = self._find_add_member_entry(elements)
        if not add_button and ui_tree:
            add_button = self._find_add_member_entry([ui_tree], is_flat_list=False)

        if not add_button:
            self.logger.warning("Could not find add-member entry")
            return False

        if not await self._tap_element(add_button):
            self.logger.warning("Could not tap add-member entry")
            return False

        await self.adb.wait(self.config.timing.tap_delay)
        return True

    async def search_and_select_member(
        self,
        device_serial: str,
        member_name: str,
        duplicate_name_policy: str = "first",
    ) -> bool:
        """Search for a member and select the first matching result."""
        _ = device_serial
        if duplicate_name_policy != "first":
            self.logger.warning(f"Unsupported duplicate policy '{duplicate_name_policy}', falling back to first")

        input_ready = await self._ensure_member_search_input_ready()
        if not input_ready:
            self.logger.warning("Could not open member search input")
            return False

        await self.adb.clear_text_field()
        await self.adb.input_text(member_name)
        await self.adb.wait(self.config.timing.ui_stabilization_delay)

        ui_tree, elements = await self.adb.get_ui_state(force=True)
        self._update_screen_dimensions(elements)
        search_input = self._find_search_input(elements)
        matches = self._find_member_result_candidates(elements, member_name, anchor=search_input)
        if not matches and ui_tree:
            matches = self._find_member_result_candidates(
                [ui_tree], member_name, anchor=search_input, is_flat_list=False
            )

        if not matches:
            self.logger.warning(f"Could not find search result for member '{member_name}'")
            return False

        if not await self._tap_element(matches[0]):
            self.logger.warning(f"Could not tap member search result for '{member_name}'")
            return False

        await self.adb.wait(self.config.timing.tap_delay)
        return True

    async def confirm_group_creation(
        self,
        device_serial: str,
        post_confirm_wait_seconds: float = 1.0,
    ) -> bool:
        """Confirm group creation and wait until chat view is ready."""
        _ = device_serial
        ui_tree, elements = await self.adb.get_ui_state(force=True)
        self._update_screen_dimensions(elements)
        confirm_button = self._find_group_confirm_button(elements)
        if not confirm_button and ui_tree:
            confirm_button = self._find_group_confirm_button([ui_tree], is_flat_list=False)

        if not confirm_button:
            self.logger.warning("Could not find confirm/create-group button")
            return False

        if not await self._tap_element(confirm_button):
            self.logger.warning("Could not tap confirm/create-group button")
            return False

        await self.adb.wait(max(post_confirm_wait_seconds, self.config.timing.tap_delay))
        # External-group creation can take noticeably longer than a normal chat
        # transition before the destination chat screen becomes detectable.
        deadline = time.monotonic() + max(post_confirm_wait_seconds, 1.0) + 30.0
        while time.monotonic() < deadline:
            if await self.get_current_screen() == "chat":
                return True
            await self.adb.wait(0.5)
        return False

    async def set_group_name(self, device_serial: str, group_name: str) -> bool:
        """Best-effort group rename hook.

        The Android flow requested for this feature does not require renaming,
        so failures here should not block the main create-group path.
        """
        _ = device_serial
        if not group_name:
            return True
        self.logger.info("Group rename is not implemented for the current Android flow")
        return False

    def _find_group_invite_menu_button(
        self,
        elements: list[dict],
        is_flat_list: bool = True,
    ) -> dict | None:
        matches = self._find_elements_by_keywords(
            elements,
            text_patterns=group_invite_selectors.CHAT_INFO_MENU_TEXT_PATTERNS,
            desc_patterns=group_invite_selectors.CHAT_INFO_MENU_DESC_PATTERNS,
            resource_patterns=group_invite_selectors.CHAT_INFO_MENU_RESOURCE_PATTERNS,
            is_flat_list=is_flat_list,
        )
        if matches:
            self.logger.debug(f"Found {len(matches)} chat-info menu candidates by keywords")
            return self._pick_top_right_element(matches)
        candidates = self._collect_header_action_candidates(elements, is_flat_list=is_flat_list)
        self.logger.debug(f"Keyword match failed; {len(candidates)} header-action fallback candidates")
        return self._pick_top_right_element(candidates)

    def _find_add_member_entry(
        self,
        elements: list[dict],
        is_flat_list: bool = True,
    ) -> dict | None:
        matches = self._find_elements_by_keywords(
            elements,
            text_patterns=group_invite_selectors.ADD_MEMBER_TEXT_PATTERNS,
            desc_patterns=group_invite_selectors.ADD_MEMBER_DESC_PATTERNS,
            resource_patterns=group_invite_selectors.ADD_MEMBER_RESOURCE_PATTERNS,
            is_flat_list=is_flat_list,
        )
        if matches:
            return self._pick_first_by_layout(matches)

        # Some WeCom builds render the add-member affordance in the member grid
        # as a bare ImageView without text/resource hints. Fall back to the
        # top member strip and pick the first image-only tile after the
        # customer's own avatar tile.
        fallback_candidates: list[dict] = []
        sw, sh = self._screen_width, self._screen_height

        def collect_fallback_candidates(items: list[dict]) -> None:
            for element in items:
                if not isinstance(element, dict):
                    continue
                class_name = (element.get("className") or "").lower()
                if any(token in class_name for token in ("image", "linearlayout", "framelayout", "viewgroup")):
                    if (
                        not element.get("text")
                        and not element.get("contentDescription")
                        and not element.get("resourceId")
                    ):
                        bounds = self._parse_element_bounds(element)
                        if bounds:
                            x1, y1, x2, y2 = bounds
                            width = x2 - x1
                            height = y2 - y1
                            if (
                                x1 >= sw * 0.19
                                and y1 >= sh * 0.10
                                and x2 <= sw * 0.52
                                and y2 <= sh * 0.28
                                and sw * 0.08 <= width <= sw * 0.32
                                and sh * 0.04 <= height <= sh * 0.15
                            ):
                                fallback_candidates.append(element)
                if not is_flat_list:
                    collect_fallback_candidates(element.get("children", []))

        collect_fallback_candidates(elements)

        if fallback_candidates:
            self.logger.info(
                f"Using image-only fallback for add-member entry ({len(fallback_candidates)} candidates, screen={sw}x{sh})"
            )
            return self._pick_first_by_layout(fallback_candidates)
        self.logger.warning(
            f"No add-member entry found (keywords={len(matches)}, fallback={len(fallback_candidates)}, screen={sw}x{sh})"
        )
        return None

    def _find_search_button(
        self,
        elements: list[dict],
        is_flat_list: bool = True,
    ) -> dict | None:
        matches = self._find_elements_by_keywords(
            elements,
            text_patterns=group_invite_selectors.SEARCH_TEXT_PATTERNS,
            desc_patterns=group_invite_selectors.SEARCH_DESC_PATTERNS,
            resource_patterns=group_invite_selectors.SEARCH_RESOURCE_PATTERNS,
            is_flat_list=is_flat_list,
        )
        if matches:
            return self._pick_top_right_element(matches)
        sw, sh = self._screen_width, self._screen_height
        header_candidates = [
            element
            for element in elements
            if isinstance(element, dict)
            and any(token in (element.get("className") or "").lower() for token in ("image", "button", "textview"))
            and (bounds := self._parse_element_bounds(element))
            and bounds[1] <= sh * 0.08
            and bounds[0] >= sw * 0.52
        ]
        if header_candidates:
            self.logger.info("Using top-right fallback for member search entry")
            return self._pick_top_right_element(header_candidates)
        return None

    def _find_group_confirm_button(
        self,
        elements: list[dict],
        is_flat_list: bool = True,
    ) -> dict | None:
        matches = self._find_elements_by_keywords(
            elements,
            text_patterns=group_invite_selectors.CONFIRM_GROUP_TEXT_PATTERNS,
            desc_patterns=group_invite_selectors.CONFIRM_GROUP_DESC_PATTERNS,
            resource_patterns=group_invite_selectors.CONFIRM_GROUP_RESOURCE_PATTERNS,
            is_flat_list=is_flat_list,
        )
        if not matches:
            self.logger.warning("No confirm/create-group button found by keywords")
            return None
        self.logger.debug(f"Found {len(matches)} confirm button candidates")
        return self._pick_bottom_right_element(matches)

    async def _ensure_member_search_input_ready(self) -> bool:
        ui_tree, elements = await self.adb.get_ui_state(force=True)
        input_field = self._find_search_input(elements)
        if input_field:
            if not await self._tap_element(input_field):
                return False
            await self.adb.wait(self.config.timing.tap_delay)
            return True

        search_button = self._find_search_button(elements)
        if not search_button and ui_tree:
            search_button = self._find_search_button([ui_tree], is_flat_list=False)

        if not search_button or not await self._tap_element(search_button):
            return False

        await self.adb.wait(self.config.timing.tap_delay)
        _, elements = await self.adb.get_ui_state(force=True)
        input_field = self._find_search_input(elements)
        if not input_field:
            return False

        if not await self._tap_element(input_field):
            return False

        await self.adb.wait(self.config.timing.tap_delay)
        return True

    def _find_search_input(self, elements: list[dict]) -> dict | None:
        inputs: list[dict] = []
        for element in elements:
            class_name = (element.get("className") or "").lower()
            text = (element.get("text") or "").lower()
            rid = (element.get("resourceId") or "").lower()
            content_desc = (element.get("contentDescription") or "").lower()
            if "edittext" in class_name or "search" in text or "search" in rid or "search" in content_desc:
                inputs.append(element)
        if not inputs:
            return None
        return self._pick_first_by_layout(inputs)

    def _find_member_result_candidates(
        self,
        elements: list[dict],
        member_name: str,
        anchor: dict | None = None,
        is_flat_list: bool = True,
    ) -> list[dict]:
        matches: list[dict] = []
        anchor_bounds = self._parse_element_bounds(anchor)
        min_y = anchor_bounds[3] if anchor_bounds else 0
        min_x = int(self._screen_width * 0.14)

        def append_matches(items: list[dict]) -> None:
            for element in items:
                text = (element.get("text") or "").strip()
                text_normalized = " ".join(text.split()).lower()
                member_name_normalized = " ".join(member_name.split()).lower()
                if (
                    text_normalized != member_name_normalized
                    and member_name_normalized not in text_normalized
                    and text_normalized not in member_name_normalized
                ):
                    if not is_flat_list:
                        append_matches(element.get("children", []))
                    continue

                bounds = self._parse_element_bounds(element)
                if bounds and bounds[1] < min_y:
                    continue
                if bounds and bounds[0] < min_x:
                    if not is_flat_list:
                        append_matches(element.get("children", []))
                    continue
                matches.append(element)

                if not is_flat_list:
                    append_matches(element.get("children", []))

        append_matches(elements)
        return sorted(matches, key=self._layout_sort_key)

    def _find_elements_by_keywords(
        self,
        elements: list[dict],
        *,
        text_patterns: tuple[str, ...] = (),
        desc_patterns: tuple[str, ...] = (),
        resource_patterns: tuple[str, ...] = (),
        is_flat_list: bool = True,
    ) -> list[dict]:
        matches: list[dict] = []

        def walk(items: list[dict]) -> None:
            for element in items:
                if not isinstance(element, dict):
                    continue
                text = (element.get("text") or "").lower()
                desc = (element.get("contentDescription") or "").lower()
                rid = (element.get("resourceId") or "").lower()

                if (
                    any(pattern.lower() in text for pattern in text_patterns)
                    or any(pattern.lower() in desc for pattern in desc_patterns)
                    or any(pattern.lower() in rid for pattern in resource_patterns)
                ):
                    matches.append(element)

                if not is_flat_list:
                    walk(element.get("children", []))

        walk(elements)
        return matches

    def _pick_top_right_element(self, elements: list[dict]) -> dict | None:
        if not elements:
            return None
        return max(elements, key=lambda element: (self._layout_x2(element), -self._layout_y1(element)))

    def _pick_bottom_right_element(self, elements: list[dict]) -> dict | None:
        if not elements:
            return None
        return max(elements, key=lambda element: (self._layout_y2(element), self._layout_x2(element)))

    def _pick_first_by_layout(self, elements: list[dict]) -> dict | None:
        if not elements:
            return None
        return sorted(elements, key=self._layout_sort_key)[0]

    def _collect_header_action_candidates(self, elements: list[dict], *, is_flat_list: bool = True) -> list[dict]:
        candidates: list[dict] = []

        def walk(items: list[dict]) -> None:
            for element in items:
                if not isinstance(element, dict):
                    continue
                if self._is_image_like_click_target(element):
                    candidates.append(element)
                if not is_flat_list:
                    walk(element.get("children", []))

        walk(elements)
        return candidates

    def _layout_sort_key(self, element: dict) -> tuple[int, int]:
        bounds = self._parse_element_bounds(element)
        if not bounds:
            return (10**9, 10**9)
        x1, y1, _, _ = bounds
        return (y1, x1)

    def _layout_x2(self, element: dict) -> int:
        bounds = self._parse_element_bounds(element)
        return bounds[2] if bounds else -1

    def _layout_y1(self, element: dict) -> int:
        bounds = self._parse_element_bounds(element)
        return bounds[1] if bounds else 10**9

    def _layout_y2(self, element: dict) -> int:
        bounds = self._parse_element_bounds(element)
        return bounds[3] if bounds else -1

    def _is_image_like_click_target(self, element: dict) -> bool:
        class_name = (element.get("className") or "").lower()
        if not any(token in class_name for token in ("image", "button", "textview", "relativelayout", "linearlayout")):
            return False
        if not (element.get("clickable") or element.get("isClickable")):
            return False
        bounds = self._parse_element_bounds(element)
        if not bounds:
            return False
        x1, y1, x2, y2 = bounds
        sw, sh = self._screen_width, self._screen_height
        return y1 <= sh * 0.12 and x1 >= sw * 0.44 and x2 >= sw * 0.52 and y2 <= sh * 0.12

    # =========================================================================
    # Debug Helpers
    # =========================================================================

    def _log_ui_elements(
        self,
        elements: list[dict],
        context: str = "",
    ) -> None:
        """Log UI elements for debugging."""
        ctx = f" ({context})" if context else ""
        self.logger.debug(f"=== UI Elements{ctx} ===")
        self._print_elements_tree(elements, max_depth=4)
        self.logger.debug("=== End UI Elements ===")

    def _print_elements_tree(
        self,
        elements: list[dict],
        indent: int = 0,
        max_depth: int = 3,
    ) -> None:
        """Print element tree structure."""
        if indent > max_depth:
            return

        for element in elements:
            text = element.get("text", "")
            index = element.get("index", "?")
            class_name = element.get("className", "")
            clickable = element.get("clickable", False)

            prefix = "  " * indent
            if text or clickable:
                click_marker = "[C]" if clickable else "   "
                self.logger.debug(f"{prefix}{click_marker} [{index}] {class_name}: '{text}'")

            children = element.get("children", [])
            if children:
                self._print_elements_tree(children, indent + 1, max_depth)
